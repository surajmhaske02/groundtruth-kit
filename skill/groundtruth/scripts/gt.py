#!/usr/bin/env python3
"""
groundtruth (gt) - evidence tools for AI-written codebases.

  python gt.py map                       build docs/CODEMAP.md (entry points, LLM/tool hotspots,
                                         dynamic dispatch, duplicates, symbol index)
  python gt.py flow TARGET [--depth N]   static call tree from a function
                                         TARGET = func | Class.method | path/file.py:func
  python gt.py callers NAME              every call site / reference / config mention of NAME
  python gt.py verify FILE|-             check that citations, symbols and quoted code in an
                                         AI answer really exist in this repo (exit 1 on failures)
  python gt.py viz [--open]              interactive HTML report: overview, flow explorer, agent run timelines
  python gt.py trace list|view|show|diff inspect agent runs recorded with agent_trace.py

Pure standard library, Python 3.8+. Full call graph for Python; symbol index for
JS/TS, Go, Java, Kotlin, C#, Rust, Ruby, PHP, Swift, Scala.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import datetime as _dt
import hashlib
import json
import keyword
import os
import pickle
import re
import sys
from collections import defaultdict
from pathlib import Path
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:  # make unicode output safe on Windows consoles
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# --------------------------------------------------------------------------- config

SKIP_DIRS = {
    "node_modules", "__pycache__", "venv", "site-packages", "dist-packages", "dist", "build", "target",
    "coverage", "htmlcov", "vendor", "eggs", "bower_components", "Pods", "DerivedData",
}
LANG_BY_EXT = {
    ".py": "py", ".pyi": "py",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".cs": "csharp",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".swift": "swift", ".scala": "scala",
    ".c": "c", ".h": "c", ".cpp": "c", ".cc": "c", ".hpp": "c",
}
CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties"}
TEXT_EXTS = set(LANG_BY_EXT) | CONFIG_EXTS | {
    ".md", ".txt", ".rst", ".sql", ".sh", ".bash", ".ps1", ".ipynb", ".html", ".css",
    ".scss", ".graphql", ".proto", ".tf", ".lock", ".env", ".example", ".dockerfile",
}
MAX_FILE_BYTES = 1_500_000
CACHE_VERSION = "gt-4"
OWN_DIR = "tools/groundtruth"

HOT_PATTERNS = [
    (r"\.chat\.completions\.create\(|\.responses\.create\(|\.messages\.create\(|\.completions\.create\(|\.messages\.stream\(", "LLM call (SDK)"),
    (r"\bgenerate_content\(|\.send_message\(", "LLM call (Gemini)"),
    (r"\blitellm\.a?completion\(|(?<![\w.])acompletion\(", "LLM call (litellm)"),
    (r"\bChat(?:OpenAI|Anthropic|Ollama|VertexAI|Bedrock\w*|Google\w*|Groq|Mistral\w*|Cohere)\(|\bAzureChatOpenAI\(", "LLM client (LangChain)"),
    (r"(?<![\w.])(?:Async)?(?:Azure)?OpenAI\(|(?<![\w.])(?:Async)?Anthropic\(|\bgenai\.Client\(", "LLM client init"),
    (r"\.a?invoke\(|\.astream(?:_events)?\(|\.stream\(", "chain/graph invoke"),
    (r"^\s*@(?:\w+\.)*(?:tool|function_tool)\b", "tool definition"),
    (r"\b(?:StructuredTool|Tool)\.from_function\(|\bFunctionTool\(|\bbind_tools\(", "tool definition"),
    (r"\bStateGraph\(|\bMessageGraph\(|\.add_node\(|\.add_conditional_edges\(|\.add_edge\(|\.set_entry_point\(|\.compile\(\s*(?:checkpointer|\))", "agent graph wiring"),
    (r"\b(?:Agent|Crew|AgentExecutor|create_react_agent|create_tool_calling_agent|initialize_agent|Swarm|Assistant)\(", "agent definition"),
    (r"\bChatPromptTemplate\b|\bPromptTemplate\b|\bSystemMessage\(|\bsystem_prompt\s*=|\bSYSTEM_PROMPT\b", "prompt"),
    (r"\bembed_documents\(|\bembed_query\(|\bembeddings\.create\(|\bsimilarity_search\w*\(|\bas_retriever\(|\.query\(\s*query_(?:texts|embeddings)", "retrieval / embeddings"),
]
DYN_PATTERNS = [
    (r"(?<![\w.])getattr\(\s*[^,()]+,\s*(?![\"'])[^)]", "getattr with computed name"),
    (r"\bimportlib\.import_module\(|(?<![\w.])__import__\(", "dynamic import"),
    (r"\bglobals\(\)\s*\[|\blocals\(\)\s*\[", "globals()/locals() lookup"),
    (r"(?<![\w.])eval\(|(?<![\w.])exec\(", "eval/exec"),
    (r"\b[A-Za-z_]\w*\[[^\]\n]+\]\s*\(", "call through dict/registry lookup"),
    (r"(?i)=\s*(?:self\.)?\w*(?:tool|handler|registry|dispatch|node|func|action|command|strateg|plugin)s?\w*\s*(?:\[(?!\d)[^\]\n]+\]|\.get\()",
     "registry lookup (callable chosen at runtime)"),
    (r"\.add_conditional_edges\(", "routing decided at runtime (state/model)"),
    (r"\bentry_points\(|\biter_entry_points\(", "plugin entry points"),
]
IO_PATTERNS = re.compile(
    r"^(?:requests|httpx|aiohttp|urllib|boto3|s3|redis|subprocess|os\.system|shutil)\b|"
    r"\.(?:execute|executemany|commit|send|publish|put_object|upload\w*|write|to_sql|to_csv|to_parquet)$|^open$"
)
ENTRY_DECOS = [
    (re.compile(r"\.(?:get|post|put|patch|delete|route|api_route|websocket)\("), "HTTP route"),
    (re.compile(r"(?:^|\.)(?:command|group|callback)\b"), "CLI command"),
    (re.compile(r"(?:^|\.)(?:task|shared_task|scheduled_job|on_event|job|cron|periodic_task)\b"), "background job"),
    (re.compile(r"(?:^|\.)(?:tool|function_tool)\b"), "agent tool"),
]
JS_ROUTE = re.compile(r"\b(?:app|router|server)\.(get|post|put|patch|delete|all)\(\s*['\"`]([^'\"`]+)")

REGEX_DEFS = {
    "js": [
        (r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<n>[A-Za-z_$][\w$]*)", "function"),
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<n>[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|[A-Za-z_$][\w$]*\s*=>)", "function"),
        (r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<n>[A-Za-z_$][\w$]*)", "class"),
        (r"^\s*(?:export\s+)?interface\s+(?P<n>[A-Za-z_$][\w$]*)", "interface"),
        (r"^\s+(?:(?:public|private|protected|static|async|readonly|override)\s+)*(?P<n>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{]+)?\{\s*$", "method"),
    ],
    "go": [
        (r"^func\s+\(\s*\w*\s*\*?\s*(?P<recv>[A-Za-z_]\w*)[^)]*\)\s*(?P<n>[A-Za-z_]\w*)\s*[\[(]", "method"),
        (r"^func\s+(?P<n>[A-Za-z_]\w*)\s*[\[(]", "function"),
        (r"^type\s+(?P<n>[A-Za-z_]\w*)\s+(?:struct|interface)\b", "class"),
    ],
    "java": [
        (r"^\s*(?:(?:public|private|protected|static|final|abstract|sealed)\s+)*(?:class|interface|enum|record)\s+(?P<n>\w+)", "class"),
        (r"^\s*(?:public|private|protected)\s+(?:(?:static|final|abstract|synchronized|default)\s+)*[\w<>\[\],.? ]+\s+(?P<n>\w+)\s*\(", "method"),
    ],
    "kotlin": [
        (r"^\s*(?:(?:public|private|protected|internal|open|data|sealed|abstract|enum)\s+)*(?:class|interface|object)\s+(?P<n>\w+)", "class"),
        (r"\bfun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(?P<n>\w+)\s*\(", "function"),
    ],
    "csharp": [
        (r"^\s*(?:(?:public|private|protected|internal|static|sealed|abstract|partial)\s+)*(?:class|interface|struct|record|enum)\s+(?P<n>\w+)", "class"),
        (r"^\s*(?:public|private|protected|internal)\s+(?:(?:static|async|override|virtual|abstract|sealed)\s+)*[\w<>\[\],.? ]+\s+(?P<n>\w+)\s*\(", "method"),
    ],
    "rust": [
        (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(?P<n>\w+)", "function"),
        (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+(?P<n>\w+)", "class"),
    ],
    "ruby": [
        (r"^\s*def\s+(?:self\.)?(?P<n>\w+[?!]?)", "function"),
        (r"^\s*(?:class|module)\s+(?P<n>[A-Z]\w*)", "class"),
    ],
    "php": [
        (r"\bfunction\s+(?P<n>\w+)\s*\(", "function"),
        (r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+(?P<n>\w+)", "class"),
    ],
    "swift": [
        (r"\bfunc\s+(?P<n>\w+)", "function"),
        (r"^\s*(?:(?:public|private|internal|open|final)\s+)*(?:class|struct|enum|protocol|actor)\s+(?P<n>\w+)", "class"),
    ],
    "scala": [
        (r"\bdef\s+(?P<n>\w+)", "function"),
        (r"^\s*(?:(?:case|abstract|sealed|final)\s+)*(?:class|object|trait)\s+(?P<n>\w+)", "class"),
    ],
    "c": [
        (r"^\s*(?:class|struct)\s+(?P<n>\w+)\s*(?:[:{]|$)", "class"),
    ],
}
JS_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "function", "else", "constructor", "super", "with"}
BUILTIN_NAMES = set(dir(builtins))
COMMON_METHODS = {n for t in (str, bytes, list, dict, set, tuple, int, float, object) for n in dir(t)} | {
    "get", "items", "keys", "values", "append", "extend", "update", "pop", "join", "split", "strip", "read",
    "write", "close", "open", "copy", "add", "remove", "sort", "encode", "decode", "format", "replace", "lower",
    "upper", "find", "count", "index", "info", "debug", "warning", "warn", "error", "exception", "critical", "log",
    "flush", "readline", "readlines", "seek", "tell", "send", "recv", "connect", "json", "group", "match",
    "search", "sub", "findall", "finditer", "fullmatch", "sleep", "wait", "result", "cancel", "done", "put",
    "get_nowait", "put_nowait", "acquire", "release", "exists", "mkdir", "glob", "iterdir", "is_file", "is_dir",
    "read_text", "write_text", "read_bytes", "with_suffix", "setdefault", "discard", "clear", "isoformat",
    "strftime", "total_seconds", "raise_for_status", "cursor", "commit", "rollback", "fetchone", "fetchall",
    "start", "end", "span", "groups", "groupdict", "lastgroup",
}
COMMON_WORDS = {"true", "false", "none", "null", "undefined", "self", "cls", "this", "todo", "fixme",
                "json", "yaml", "http", "https", "get", "set", "put", "post", "api", "main"}


def _compile(pats):
    return [(re.compile(p), label) for p, label in pats]


HOT_RE = _compile(HOT_PATTERNS)
DYN_RE = _compile(DYN_PATTERNS)
REGEX_DEFS_C = {lang: [(re.compile(p), kind) for p, kind in pats] for lang, pats in REGEX_DEFS.items()}

# --------------------------------------------------------------------------- helpers


def find_root(start: Path) -> Path:
    p = start.resolve()
    for q in [p, *p.parents]:
        if (q / ".git").exists():
            return q
    return p


def get_root(args) -> Path:
    """--root is used as given; otherwise the nearest folder with .git above the cwd."""
    return Path(args.root).expanduser().resolve() if getattr(args, "root", None) else find_root(Path("."))


def rel_of(root: Path, p: Path) -> str:
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def walk_files(root: Path, exts=None):
    """Yield files under root, skipping vendored/virtualenv/hidden/build dirs and our own tools."""
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        rel = rel_of(root, dp)
        if rel == OWN_DIR or rel.startswith(OWN_DIR + "/"):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and not (dp / d / "pyvenv.cfg").exists()
        )
        for f in sorted(filenames):
            p = dp / f
            if exts is not None and p.suffix.lower() not in exts:
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def src_of(node) -> str:
    """Readable source for an AST node (ast.unparse on 3.9+, dotted-name fallback on 3.8)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        d = _dotted(node)
        if "..." not in d:
            return d
    try:
        s = ast.unparse(node)  # type: ignore[attr-defined]
    except Exception:
        s = _dotted(node)
    s = " ".join(s.split())
    return s if len(s) <= 90 else s[:87] + "..."


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + "." + node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func) + "(...)"
    if isinstance(node, ast.Subscript):
        return _dotted(node.value) + "[...]"
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return "..."


_STDLIB_CACHE: dict = {}


def is_stdlib(name: str) -> bool:
    if name in _STDLIB_CACHE:
        return _STDLIB_CACHE[name]
    names = getattr(sys, "stdlib_module_names", None)  # 3.10+
    if names is not None:
        ok = name in names
    else:
        ok = name in sys.builtin_module_names
        if not ok:
            try:
                import importlib.util
                import sysconfig
                spec = importlib.util.find_spec(name)
                std = os.path.normcase(sysconfig.get_paths()["stdlib"])
                origin = os.path.normcase(getattr(spec, "origin", "") or "")
                ok = bool(spec) and origin.startswith(std) and "site-packages" not in origin
            except Exception:
                ok = False
    _STDLIB_CACHE[name] = ok
    return ok


def is_comment(line: str) -> bool:
    s = line.lstrip()
    return s.startswith(("#", "//", "*", "/*", "--"))


def modpath_of(rel: str) -> str:
    m = rel[:-3] if rel.endswith(".py") else rel
    if m.endswith("/__init__"):
        m = m[: -len("/__init__")]
    return m.replace("/", ".")


class Sym:
    __slots__ = ("name", "qual", "kind", "file", "line", "end", "lang", "calls", "decos", "doc", "clone_hash", "cls", "types")

    def __init__(self, name, qual, kind, file, line, end, lang, calls=None, decos=None, doc="", clone_hash=None, cls=None,
                 types=None):
        self.name, self.qual, self.kind, self.file, self.line, self.end = name, qual, kind, file, line, end
        self.lang, self.calls, self.decos, self.doc, self.clone_hash, self.cls = lang, calls or [], decos or [], doc, clone_hash, cls
        self.types = types or {}   # local var / self.attr -> class name (from `x = Cls()`, annotations)

    @property
    def loc(self):
        return f"{self.file}:{self.line}"

    def to_json(self):
        return {"name": self.name, "qual": self.qual, "kind": self.kind, "file": self.file,
                "line": self.line, "end": self.end, "lang": self.lang}


def _stmt_lists(node):
    for attr in ("body", "orelse", "finalbody"):
        v = getattr(node, attr, None)
        if isinstance(v, list):
            yield v
    for h in getattr(node, "handlers", []) or []:
        yield h.body
    for c in getattr(node, "cases", []) or []:
        yield c.body


def _nested_defs(stmts):
    """Defs inside a function body, including inside if/for/try blocks, not inside other defs."""
    for s in stmts:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield s
        elif isinstance(s, ast.stmt):
            for lst in _stmt_lists(s):
                yield from _nested_defs(lst)


# --------------------------------------------------------------------------- index


class Index:
    def __init__(self, root: Path):
        self.root = root
        self.syms: list[Sym] = []
        self.by_name = defaultdict(list)
        self.by_qual = defaultdict(list)
        self.file_lines: dict[str, list[str]] = {}
        self.file_doc: dict[str, str] = {}
        self.imports: dict[str, dict] = defaultdict(dict)   # file -> local -> (module, orig)
        self.imported_names: set[str] = set()                # every local alias of an import
        self.entries: list[tuple] = []                       # (loc, kind, what)
        self.hot: dict[str, list] = defaultdict(list)        # label -> [(loc, text)]
        self.dynamic: dict[str, list] = defaultdict(list)
        self.parse_errors: list[tuple] = []
        self.idents: set[str] = set()
        self.norm_lines: set[str] = set()
        self.notebooks: list[str] = []
        self.config_files: list[str] = []
        self.code_files: list[str] = []
        self.attr_types = defaultdict(dict)                  # (file, class qual) -> {"self.x": ClassName}

    # ---- build (per-file results cached in .groundtruth/cache.pkl, keyed by mtime+size)
    def build(self):
        cache_path = self.root / ".groundtruth" / "cache.pkl"
        cache, fresh, dirty = {}, {}, False
        try:
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            if data.get("v") == CACHE_VERSION:
                cache = data["files"]
        except Exception:
            pass
        self.code_files = []
        for p in walk_files(self.root):
            ext = p.suffix.lower()
            rel = rel_of(self.root, p)
            if ext == ".ipynb":
                self.notebooks.append(rel)
                continue
            if ext in CONFIG_EXTS:
                self.config_files.append(rel)
                continue
            lang = LANG_BY_EXT.get(ext)
            if not lang:
                continue
            self.code_files.append(rel)
            try:
                st = p.stat()
                key = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
            hit = cache.get(rel)
            if hit and hit[0] == key:
                res = hit[1]
            else:
                res = self._index_file(rel, lang, read_text(p))
                dirty = True
            fresh[rel] = (key, res)
            self._merge(rel, res)
        if dirty or len(fresh) != len(cache):
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, "wb") as f:
                    pickle.dump({"v": CACHE_VERSION, "files": fresh}, f, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:
                pass
        for s in self.syms:
            self.by_name[s.name].append(s)
            self.by_qual[s.qual].append(s)
            owner = s.qual if s.kind == "class" else s.cls
            if owner and s.types:
                self.attr_types[(s.file, owner)].update({k: v for k, v in s.types.items() if k.startswith("self.")})
        return self

    def _index_file(self, rel, lang, text):
        sub = Index(self.root)
        lines = text.splitlines()
        if lang == "py":
            sub._index_py(rel, text, lines)
        else:
            sub._index_regex(rel, lang, lines)
        sub._scan_lines(rel, lang, lines)
        return {"syms": sub.syms, "doc": sub.file_doc.get(rel), "imports": dict(sub.imports.get(rel, {})),
                "imported_names": sub.imported_names, "entries": sub.entries, "hot": dict(sub.hot),
                "dynamic": dict(sub.dynamic), "parse_errors": sub.parse_errors}

    def _merge(self, rel, r):
        self.syms.extend(r["syms"])
        if r["doc"]:
            self.file_doc[rel] = r["doc"]
        if r["imports"]:
            self.imports[rel] = r["imports"]
        self.imported_names |= r["imported_names"]
        self.entries.extend(r["entries"])
        for k, v in r["hot"].items():
            self.hot[k].extend(v)
        for k, v in r["dynamic"].items():
            self.dynamic[k].extend(v)
        self.parse_errors.extend(r["parse_errors"])

    def load_text(self):
        """Source lines, identifier set and normalised lines (needed by callers/verify, not by map/flow)."""
        if self.file_lines:
            return self
        for rel in self.code_files:
            text = read_text(self.root / rel)
            lines = text.splitlines()
            self.file_lines[rel] = lines
            self.idents.update(re.findall(r"[A-Za-z_$][\w$]*", text))
            for ln in lines:
                n = " ".join(ln.split())
                if len(n) > 12:
                    self.norm_lines.add(n)
        for rel in self.config_files:
            self.idents.update(re.findall(r"[A-Za-z_][\w]*", read_text(self.root / rel)))
        return self

    def _add(self, s: Sym):
        self.syms.append(s)

    def _index_regex(self, rel, lang, lines):
        cur_class, class_indent = None, 0
        for i, line in enumerate(lines, 1):
            if is_comment(line):
                continue
            indent = len(line) - len(line.lstrip())
            if cur_class and (line.startswith("}") or (indent <= class_indent and line.strip() == "end")):
                cur_class = None
            for rx, kind in REGEX_DEFS_C.get(lang, []):
                m = rx.search(line)
                if m:
                    name = m.group("n")
                    if lang == "js" and kind == "method" and name in JS_NOT_METHODS:
                        continue
                    qual, owner = name, None
                    recv = m.groupdict().get("recv")
                    if recv:                                    # Go: func (s *Server) Handle()
                        qual, owner, kind = f"{recv}.{name}", recv, "method"
                    elif kind in ("class", "interface"):
                        cur_class, class_indent = name, indent
                    elif cur_class and indent > class_indent:  # method inside a class body
                        qual, owner, kind = f"{cur_class}.{name}", cur_class, "method"
                    self._add(Sym(name, qual, kind, rel, i, i, lang, cls=owner))
                    break
            if lang == "js":
                m = JS_ROUTE.search(line)
                if m:
                    self.entries.append((f"{rel}:{i}", "HTTP route", f"{m.group(1).upper()} {m.group(2)}"))

    def _scan_lines(self, rel, lang, lines):
        for i, line in enumerate(lines, 1):
            if is_comment(line) and not line.lstrip().startswith("@"):
                continue
            for rx, label in HOT_RE:
                if rx.search(line):
                    self.hot[label].append((f"{rel}:{i}", line.strip()[:100]))
                    break
            if lang in ("py", "js"):
                for rx, label in DYN_RE:
                    if rx.search(line):
                        self.dynamic[label].append((f"{rel}:{i}", line.strip()[:100]))
                        break

    def _index_py(self, rel, text, lines):
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            self.parse_errors.append((rel, e.lineno or 0, e.msg))
            for i, line in enumerate(lines, 1):
                m = re.match(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*class\s+(\w+)", line)
                if m:
                    n = m.group(1) or m.group(2)
                    self._add(Sym(n, n, "function" if m.group(1) else "class", rel, i, i, "py"))
            return
        doc = ast.get_docstring(tree)
        if doc:
            self.file_doc[rel] = doc.strip().splitlines()[0][:100]
        mod = modpath_of(rel)
        pkg = mod.split(".")[:-1] if not rel.endswith("__init__.py") else mod.split(".")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    local = a.asname or a.name.split(".")[0]
                    self.imports[rel][local] = (a.name if a.asname else a.name.split(".")[0], None)
                    self.imported_names.add(local)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parent = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                    base = ".".join([*parent, base] if base else parent)
                for a in node.names:
                    local = a.asname or a.name
                    self.imports[rel][local] = (base, a.name)
                    if a.name != "*":
                        self.imported_names.add(local)
        for node in tree.body:
            t = getattr(node, "test", None)
            if isinstance(node, ast.If) and isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) \
                    and t.left.id == "__name__" and t.comparators and isinstance(t.comparators[0], ast.Constant) \
                    and t.comparators[0].value == "__main__":
                self.entries.append((f"{rel}:{node.lineno}", "script entry", 'if __name__ == "__main__"'))
        self._visit(rel, tree.body, cls=None, outer=None)
        # module-level code (graph wiring, registries, scripts) as a pseudo-symbol "<module>"
        top = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                                             ast.Import, ast.ImportFrom))]
        if top:
            holder = type("M", (), {"body": top})()
            self._add(Sym("<module>", f"<module {mod}>", "module", rel, 1, len(lines), "py",
                          calls=_collect_calls(holder)))

    def _visit(self, rel, stmts, cls, outer):
        for node in stmts:
            if isinstance(node, ast.ClassDef):
                qual = f"{cls}.{node.name}" if cls else (f"{outer}.<locals>.{node.name}" if outer else node.name)
                doc = (ast.get_docstring(node) or "").strip().splitlines()[:1]
                calls = [("base", b_short, src_of(b), node.lineno) for b in node.bases
                         for b_short in [_short(b)] if b_short]
                ctypes = {}
                for st in node.body:  # dataclass / pydantic style fields: name: Type
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        t = _type_name(st.annotation)
                        if t:
                            ctypes["self." + st.target.id] = t
                self._add(Sym(node.name, qual, "class", rel, node.lineno, getattr(node, "end_lineno", node.lineno), "py",
                              calls=calls, decos=[src_of(d) for d in node.decorator_list], doc=doc[0] if doc else "",
                              types=ctypes))
                self._visit(rel, node.body, cls=qual, outer=None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if cls:
                    qual, kind = f"{cls}.{node.name}", "method"
                elif outer:
                    qual, kind = f"{outer}.<locals>.{node.name}", "function"
                else:
                    qual, kind = node.name, "function"
                if isinstance(node, ast.AsyncFunctionDef):
                    kind = "async " + kind
                decos = [src_of(d) for d in node.decorator_list]
                doc = (ast.get_docstring(node) or "").strip().splitlines()[:1]
                sym = Sym(node.name, qual, kind, rel, node.lineno, getattr(node, "end_lineno", node.lineno), "py",
                          calls=_collect_calls(node), decos=decos, doc=doc[0] if doc else "",
                          clone_hash=_clone_hash(node), cls=cls, types=_local_types(node))
                self._add(sym)
                for d in decos:
                    for rx, label in ENTRY_DECOS:
                        if rx.search(d):
                            self.entries.append((sym.loc, label, f"@{d} -> {qual}"))
                            break
                if not cls and not outer and node.name in ("main", "handler", "lambda_handler", "run", "app"):
                    self.entries.append((sym.loc, "entry function", qual))
                self._visit(rel, list(_nested_defs(node.body)), cls=None, outer=qual)
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)) \
                    or type(node).__name__ in ("TryStar", "Match"):
                for lst in _stmt_lists(node):
                    self._visit(rel, lst, cls=cls, outer=outer)

    # ---- resolution
    def _class_syms(self, name_or_qual, ctx_file=None):
        """Classes matching a name, preferring the one defined in / imported into ctx_file."""
        short = name_or_qual.split(".")[-1]
        cands = [c for c in self.by_name.get(short, []) if c.kind == "class" and (c.qual == name_or_qual or c.name == name_or_qual
                                                                                  or c.qual.endswith("." + name_or_qual))]
        if ctx_file and len(cands) > 1:
            same = [c for c in cands if c.file == ctx_file]
            if same:
                return same
            imp = self.imports.get(ctx_file, {}).get(short)
            if imp:
                hit = [c for c in cands if _mod_match(modpath_of(c.file), imp[0])]
                if hit:
                    return hit
        return cands

    def _class_of(self, sym: Sym):
        """The class Sym that contains a method."""
        if not sym.cls:
            return None
        for c in self.by_qual.get(sym.cls, []):
            if c.kind == "class" and c.file == sym.file and c.line <= sym.line <= max(c.end, c.line):
                return c
        return None

    def _method_of_class(self, cls: Sym, meth, depth=0, seen=None):
        """meth defined on this exact class, else inherited from its bases (same-file/imported bases first)."""
        seen = seen if seen is not None else set()
        if cls is None or id(cls) in seen or depth > 6:
            return []
        seen.add(id(cls))
        own = [s for s in self.by_qual.get(f"{cls.qual}.{meth}", [])
               if s.file == cls.file and cls.line <= s.line <= max(cls.end, cls.line) and "method" in s.kind]
        if own:
            return own[:1]
        for base in [c[1] for c in cls.calls if c[0] == "base"]:
            for b in self._class_syms(base, cls.file)[:2]:
                hit = self._method_of_class(b, meth, depth + 1, seen)
                if hit:
                    return hit
        return []

    def _method(self, cls_name_or_qual, meth, ctx_file=None):
        for c in self._class_syms(cls_name_or_qual, ctx_file)[:3]:
            hit = self._method_of_class(c, meth)
            if hit:
                return hit
        return []

    def _attr_type(self, cls: Sym, attr, depth=0):
        if cls is None or depth > 6:
            return None
        t = self.attr_types.get((cls.file, cls.qual), {}).get(attr)
        if t:
            return t
        for base in [c[1] for c in cls.calls if c[0] == "base"]:
            for b in self._class_syms(base, cls.file)[:2]:
                t = self._attr_type(b, attr, depth + 1)
                if t:
                    return t
        return None

    def resolve(self, kind, short, disp, caller: Sym):
        """Return (status, [syms]). status: ok | probable | ambiguous | external | builtin | dynamic.
        Follows Python name lookup: a bare name must be local, nested, module-level, imported or builtin."""
        if kind == "dyn":
            return "dynamic", []
        cands = [s for s in self.by_name.get(short, []) if s.kind != "module" and (s.lang == "py") == (caller.lang == "py")]
        if caller.lang != "py":  # regex-indexed languages: name match only
            if not cands:
                return "external", []
            same = [s for s in cands if s.file == caller.file]
            if len(same) == 1:
                return "ok", same
            return ("probable", cands) if len(cands) == 1 else ("ambiguous", cands)
        parts = disp.split(".")
        head = parts[0]
        imps = self.imports.get(caller.file, {})

        if len(parts) == 1:
            if short in caller.types and kind == "ref":
                return "external", []                      # a local variable, not a function
            nested = [s for s in cands if s.qual == f"{caller.qual}.<locals>.{short}"]
            if nested:
                return "ok", nested
            local = [s for s in cands if s.file == caller.file and "." not in s.qual]
            if len(local) == 1:
                return "ok", local
            if len(local) > 1:
                return "ambiguous", local
            if short in imps:
                mod, orig = imps[short]
                hit = [s for s in cands if "." not in s.qual and s.name == orig and _mod_match(modpath_of(s.file), mod)]
                if len(hit) == 1:
                    return "ok", hit
                top = [s for s in cands if "." not in s.qual]
                if len(top) == 1:
                    return "probable", top                 # e.g. re-exported through __init__.py
                return ("ambiguous", top) if top else ("external", [])
            if short in BUILTIN_NAMES:
                return "builtin", []
            if "*" in imps:
                top = [s for s in cands if "." not in s.qual]
                if len(top) == 1:
                    return "probable", top
            return "external", []

        meth = parts[-1]
        # self.meth() / cls.meth() — own class, then base classes
        if head in ("self", "cls") and caller.cls and len(parts) == 2:
            hit = self._method_of_class(self._class_of(caller), meth)
            if hit:
                return "ok", hit[:1]
        # self.x.meth() where self.x = SomeClass(...) or x: SomeClass
        if head in ("self", "cls") and caller.cls and len(parts) == 3:
            t = self._attr_type(self._class_of(caller), f"self.{parts[1]}")
            if t:
                hit = self._method(t, meth, caller.file)
                if hit:
                    return "ok", hit[:1]
                return "external", []
        # var.meth() where var = SomeClass(...) or var: SomeClass
        if len(parts) == 2 and caller.types.get(head):
            hit = self._method(caller.types[head], meth, caller.file)
            if hit:
                return "ok", hit[:1]
            return "external", []
        # module.func() / ImportedClass.meth()
        if head in imps:
            mod, orig = imps[head]
            target = f"{mod}.{orig}" if orig else mod
            if len(parts) == 2:
                hit = [s for s in cands if "." not in s.qual and _mod_match(modpath_of(s.file), target)]
                if len(hit) == 1:
                    return "ok", hit
                hit = self._method(orig or head, meth, caller.file)
                if hit:
                    return "ok", hit[:1]
            return "external", []
        # LocalClass.meth()
        if len(parts) == 2 and head[:1].isupper():
            hit = self._method(head, meth, caller.file)
            if hit:
                return "ok", hit[:1]
        if head in BUILTIN_NAMES or meth in COMMON_METHODS or meth.startswith("__"):
            return "external", []
        meths = [s for s in cands if "method" in s.kind]
        if len(meths) == 1:
            return "probable", meths
        if len(meths) > 1:
            return "ambiguous", meths
        return "external", []

    def role_of(self, s: Sym):
        """llm | tool | graph | retrieval | None — what this function *does*, from its body and decorators."""
        if not hasattr(self, "_roles"):
            self._roles = {}
            spans = defaultdict(list)
            for label, items in self.hot.items():
                role = ("llm" if "LLM" in label or "invoke" in label else "tool" if "tool" in label
                        else "graph" if "graph" in label or "agent" in label else "retrieval" if "retrieval" in label else None)
                if role:
                    for loc, _ in items:
                        f, _, ln = loc.rpartition(":")
                        spans[f].append((int(ln), role))
            self._spans = spans
        if s.qual in self._roles:
            return self._roles[s.qual]
        role = None
        for d in s.decos:
            m = re.search(r"kind\s*=\s*['\"](\w+)", d)
            if m and m.group(1) in ("llm", "tool", "retrieval"):
                role = m.group(1)
            elif re.search(r"(?:^|\.)(?:tool|function_tool)\b", d):
                role = "tool"
        if role is None and "function" in s.kind or role is None and "method" in s.kind:
            prio = {"llm": 0, "tool": 1, "retrieval": 2, "graph": 3}
            for ln, r in self._spans.get(s.file, []):
                if s.line <= ln <= s.end and (role is None or prio[r] < prio[role]):
                    role = r
        self._roles[s.qual] = role
        return role

    def find_targets(self, target: str):
        if ":" in target and not target.startswith(":"):
            path, name = target.rsplit(":", 1)
            path = path.replace("\\", "/")
            if name.isdigit():
                ln = int(name)
                hits = [s for s in self.syms if (s.file == path or s.file.endswith("/" + path))
                        and s.line <= ln <= max(s.end, s.line) and s.kind != "class"]
                hits.sort(key=lambda s: s.line, reverse=True)
                return hits[:1]
            return [s for s in self.syms if (s.file == path or s.file.endswith("/" + path))
                    and (s.qual == name or s.name == name)]
        exact = self.by_qual.get(target, [])
        if exact:
            return exact
        return [s for s in self.by_name.get(target.split(".")[-1], []) if s.qual.endswith(target)]


def _short(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mod_match(modpath: str, target: str) -> bool:
    return modpath == target or modpath.endswith("." + target) or target.endswith("." + modpath) or \
        target.startswith(modpath + ".") and target[len(modpath) + 1:].count(".") == 0


def _collect_calls(fn):
    """(kind, short, display, line) for calls and function references inside fn (not nested defs)."""
    out = []
    seen = set()

    def ref(e, ln):
        if isinstance(e, (ast.Name, ast.Attribute)):
            k = ("ref", _short(e), getattr(e, "lineno", ln))
            if k not in seen:
                seen.add(k)
                out.append(("ref", _short(e), src_of(e), getattr(e, "lineno", ln)))

    # variables bound to a registry lookup: tool = TOOLS[name] / handlers.get(kind) / getattr(obj, attr)
    dyn_vars = {}
    for n in _walk_no_defs(fn.body):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = n.value
            if isinstance(v, ast.Subscript) and not isinstance(_slice_of(v), ast.Constant) or \
                    isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "get" or \
                    isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "getattr":
                dyn_vars[n.targets[0].id] = src_of(v)

    stack = list(fn.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in dyn_vars:
                out.append(("dyn", None, f"{f.id}(...) where {f.id} = {dyn_vars[f.id]}", n.lineno))
            elif isinstance(f, (ast.Name, ast.Attribute)):
                out.append(("call", _short(f), src_of(f), n.lineno))
            elif isinstance(f, ast.Subscript):
                out.append(("dyn", None, src_of(f) + "(...)", n.lineno))
            for a in list(n.args) + [k.value for k in n.keywords]:
                ref(a, n.lineno)                      # foo(callback), add_node("x", fn)
        elif isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            for e in n.elts:
                ref(e, n.lineno)                      # tools=[search, calc]
        elif isinstance(n, ast.Dict):
            for e in n.values:
                ref(e, n.lineno)                      # HANDLERS = {"a": handle_a}
        elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.Return)) and n.value is not None:
            ref(n.value, n.lineno)                    # handler = handle_a
        stack.extend(ast.iter_child_nodes(n))
    out.sort(key=lambda c: (c[3], c[0] != "call"))
    return out


def _type_name(ann):
    """Class name from an annotation: Foo, mod.Foo, Optional[Foo], 'Foo', Foo | None."""
    if ann is None:
        return None
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        name = ann.value.split("[")[-1].strip("] ").split(".")[-1]
        return name if name[:1].isupper() else None
    if isinstance(ann, (ast.Name, ast.Attribute)):
        n = _short(ann)
        return n if n and n[:1].isupper() and n not in ("Any", "Optional", "List", "Dict") else None
    if isinstance(ann, ast.Subscript) and _short(ann.value) in ("Optional", "Annotated", "Type"):
        inner = _slice_of(ann)
        return _type_name(inner.elts[0] if isinstance(inner, ast.Tuple) else inner)
    if isinstance(ann, ast.BinOp):  # Foo | None
        return _type_name(ann.left) or _type_name(ann.right)
    return None


def _local_types(fn):
    """var -> class name, from `x = Cls(...)`, `self.x = Cls(...)`, `x: Cls = ...` and typed parameters."""
    t = {}
    a = fn.args
    for arg in list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs):
        n = _type_name(arg.annotation)
        if n:
            t[arg.arg] = n
    for n in _walk_no_defs(fn.body):
        if isinstance(n, ast.Assign):
            targets, value, ann = n.targets, n.value, None
        elif isinstance(n, ast.AnnAssign):
            targets, value, ann = [n.target], n.value, n.annotation
        else:
            continue
        cname = _type_name(ann)
        if not cname and isinstance(value, ast.Call):
            c = _short(value.func)
            cname = c if c and c[:1].isupper() else None
        for tg in targets:
            if isinstance(tg, ast.Name):
                if cname:
                    t[tg.id] = cname
                else:
                    t.setdefault(tg.id, "")                 # known local variable, type unknown
            elif cname and isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id in ("self", "cls"):
                t["self." + tg.attr] = cname
    for arg in list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs) + \
            [x for x in (a.vararg, a.kwarg) if x is not None]:
        t.setdefault(arg.arg, "")
    return t


def _walk_no_defs(stmts):
    stack = list(stmts)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _slice_of(sub):
    s = sub.slice
    return getattr(s, "value", s) if type(s).__name__ == "Index" else s  # py3.8 wraps in ast.Index


def _clone_hash(fn):
    """Structural fingerprint of a function body with every local name replaced by '_'.
    Catches copy-paste clones whose variables were renamed (very common in AI-written code)."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return None
    h = hashlib.md5()
    count = 0
    upd = h.update
    for stmt in body:
        for node in ast.walk(stmt):
            count += 1
            upd(type(node).__name__.encode())
            for f, v in ast.iter_fields(node):
                if isinstance(v, list):
                    upd(b"#%d" % len(v))
                elif not isinstance(v, ast.AST):
                    upd(b"_" if f in ("id", "arg") else (f + "=" + repr(v)).encode())
    return h.hexdigest() if count >= 30 else None


# --------------------------------------------------------------------------- map


def _is_test(f):
    b = Path(f).name
    return "/tests/" in "/" + f or "/test/" in "/" + f or b.startswith("test_") or \
        b.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.js", ".spec.js"))


def find_duplicates(idx):
    """(same top-level name in several files, groups of renamed copy-paste clones) — test files excluded."""
    dup = {n: [s for s in ss if s.kind not in ("class", "module") and "." not in s.qual and not _is_test(s.file)]
           for n, ss in idx.by_name.items()}
    dup = {n: ss for n, ss in dup.items()
           if len({s.file for s in ss}) > 1 and not n.startswith("__") and n not in ("main", "setup", "test", "run")}
    groups = defaultdict(list)
    for s in idx.syms:
        if s.clone_hash and not _is_test(s.file):
            groups[s.clone_hash].append(s)
    return dup, [ss for ss in groups.values() if len(ss) > 1]


def cmd_map(args):
    root = get_root(args)
    idx = Index(root).build()
    out = Path(args.out) if args.out else root / "docs" / "CODEMAP.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    nfiles = len(idx.code_files)
    L = []
    w = L.append
    w("# CODEMAP")
    w("")
    w("> Generated by `python tools/groundtruth/gt.py map` — do not edit by hand, regenerate after changes.")
    w(f"> {nfiles} code files · {len(idx.syms)} symbols · root `{root.name}`")
    w("> Static index: it shows where things are *defined*, not what runs. Confirm runtime behaviour with tests/traces.")
    w("")
    w("How to use: find the entry point or hotspot → `gt.py flow <function>` → read each hop → trace at runtime.")
    w("")

    w("## Entry points")
    w("")
    if idx.entries:
        w("| Where | Kind | What |\n|---|---|---|")
        for loc, kind, what in sorted(set(idx.entries)):
            w(f"| `{loc}` | {kind} | `{what}` |")
    else:
        w("_None detected automatically. Add them to AGENTS.md → Project facts._")
    w("")

    w("## Agentic hotspots (LLM calls, tools, graphs, prompts, retrieval)")
    w("")
    if idx.hot:
        for label in [lbl for _, lbl in HOT_PATTERNS if lbl in idx.hot]:
            items = idx.hot[label]
            w(f"**{label}** ({len(items)})")
            for loc, text in items[:40]:
                w(f"- `{loc}` — `{text}`")
            if len(items) > 40:
                w(f"- … {len(items) - 40} more (`rg` to list all)")
            w("")
    else:
        w("_No LLM/agent patterns detected._\n")

    w("## Dynamic dispatch — static analysis cannot follow these, verify at runtime")
    w("")
    if idx.dynamic:
        for label, items in idx.dynamic.items():
            w(f"**{label}** ({len(items)})")
            for loc, text in items[:25]:
                w(f"- `{loc}` — `{text}`")
            if len(items) > 25:
                w(f"- … {len(items) - 25} more")
            w("")
    else:
        w("_None detected._\n")

    w("## Possible duplicates (common in AI-written code — check which one actually runs)")
    w("")
    dup_names, clones = find_duplicates(idx)
    if dup_names:
        w("**Same top-level function name defined in several files**")
        for n, ss in sorted(dup_names.items())[:60]:
            w(f"- `{n}`: " + ", ".join(f"`{s.loc}`" for s in ss))
        w("")
    if clones:
        w("**Same body (after renaming variables) under different names/places**")
        for ss in clones[:60]:
            w("- " + " ≈ ".join(f"`{s.qual}` (`{s.loc}`)" for s in ss))
        w("")
    if not dup_names and not clones:
        w("_None detected._\n")

    if idx.parse_errors:
        w("## Files that failed to parse (index is partial there)")
        w("")
        for rel, ln, msg in idx.parse_errors:
            w(f"- `{rel}:{ln}` — {msg}")
        w("")
    if idx.notebooks:
        w("## Notebooks (not indexed — move reusable logic into .py modules)")
        w("")
        for nb in idx.notebooks[:50]:
            w(f"- `{nb}`")
        w("")

    w("## Files and symbols")
    w("")
    by_file = defaultdict(list)
    for s in idx.syms:
        by_file[s.file].append(s)
    detail = "full" if nfiles <= 300 else ("top" if nfiles <= 1500 else "count")
    if detail != "full":
        w(f"_Large repo ({nfiles} files): showing {'top-level symbols only' if detail == 'top' else 'symbol counts only'}. "
          "Use `gt.py flow` / `gt.py callers` / `rg` for detail._")
        w("")
    for rel in sorted(idx.code_files):
        ss = sorted(by_file.get(rel, []), key=lambda s: s.line)
        head = f"### `{rel}`"
        if rel in idx.file_doc:
            head += f" — {idx.file_doc[rel]}"
        if detail == "count":
            w(f"- `{rel}` — {len(ss)} symbols")
            continue
        w(head)
        for s in ss:
            if "<locals>" in s.qual or s.kind == "module":
                continue
            depth = s.qual.count(".")
            if detail == "top" and depth:
                continue
            sig = "()" if "function" in s.kind or "method" in s.kind else ""
            extra = f" — {s.doc[:80]}" if s.doc else ""
            deco = f" `@{s.decos[0]}`" if s.decos else ""
            w(f"{'  ' * depth}- {s.kind} `{s.qual}{sig}` L{s.line}{deco}{extra}")
        w("")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")

    gt_dir = root / ".groundtruth"
    gt_dir.mkdir(exist_ok=True)
    (gt_dir / "index.json").write_text(json.dumps({
        "root": str(root), "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "symbols": [s.to_json() for s in idx.syms],
        "entries": [{"loc": a, "kind": b, "what": c} for a, b, c in idx.entries],
    }, indent=1), encoding="utf-8")
    print(f"CODEMAP written: {rel_of(root, out)}  ({nfiles} files, {len(idx.syms)} symbols, "
          f"{len(idx.entries)} entry points, {sum(len(v) for v in idx.hot.values())} agentic hotspots, "
          f"{sum(len(v) for v in idx.dynamic.values())} dynamic spots, {len(dup_names)} duplicate names, {len(clones)} clone groups)")
    return 0


# --------------------------------------------------------------------------- flow


def _tag(disp: str):
    for rx, label in HOT_RE:
        if rx.search(disp + "("):
            for key, tag in (("LLM", "LLM"), ("tool", "TOOL"), ("invoke", "INVOKE"), ("graph", "GRAPH"),
                             ("retrieval", "RETRIEVAL"), ("prompt", "PROMPT"), ("agent", "AGENT")):
                if key in label:
                    return tag
            return "AI"
    if IO_PATTERNS.search(disp):
        return "IO"
    return None


def children_of(idx, sym: Sym):
    """Constructing a class runs its __init__, so a class's 'calls' are its __init__'s calls."""
    if sym.kind == "class":
        init = idx._method_of_class(sym, "__init__")
        return (init[0], init[0].calls) if init else (sym, [])
    return sym, sym.calls


def edges_of(idx, sym: Sym, show_all=False):
    """Resolved outgoing edges of one symbol -> (owner, [edge dicts], hidden_external_count)."""
    owner, calls = children_of(idx, sym)
    out, hidden, done = [], 0, set()
    for kind, short, disp, ln in calls:
        if kind == "base" or (kind, disp) in done:
            continue
        done.add((kind, disp))
        status, res = idx.resolve(kind, short, disp, owner)
        if kind == "ref" and status != "ok":
            continue  # only show callbacks we can pin to one definition
        e = {"kind": kind, "disp": disp, "line": ln, "status": status, "tag": _tag(disp), "target": None, "cands": []}
        if status in ("external", "builtin"):
            if kind == "ref":
                continue
            if e["tag"] or show_all:
                out.append(e)
            else:
                hidden += 1
            continue
        if status == "ambiguous":
            e["cands"] = res
        elif status != "dynamic":
            if res[0] is owner and kind == "ref":
                continue
            e["target"] = res[0]
        out.append(e)
    return owner, out, hidden


def flow_tree(idx, start: Sym, depth: int, show_all=False):
    stats = defaultdict(int)
    seen = {start.qual}

    def walk(sym, d, stack):
        _, edges, hidden = edges_of(idx, sym, show_all)
        kids = []
        for e in edges:
            node = {"edge": e, "children": [], "hidden": 0, "note": ""}
            t = e["target"]
            if t is not None:
                stats["functions"] += 1
                if t.qual in stack:
                    node["note"] = "recursive"
                elif t.qual in seen:
                    node["note"] = "seen"
                elif d < depth:
                    seen.add(t.qual)
                    node["children"], node["hidden"] = walk(t, d + 1, stack + (t.qual,))
            else:
                stats[e["status"] if e["status"] in ("dynamic", "ambiguous") else (e["tag"] or "external")] += 1
            kids.append(node)
        return kids, hidden

    children, hidden = walk(start, 1, (start.qual,))
    return {"sym": start, "children": children, "hidden": hidden}, stats


def render_flow_text(tree):
    lines = [f"{tree['sym'].qual}  {tree['sym'].loc}"]

    def rec(nodes, hidden, prefix):
        for i, n in enumerate(nodes):
            e, t = n["edge"], n["edge"]["target"]
            last = i == len(nodes) - 1 and not hidden
            where = f"@L{e['line']}"
            if t is None and e["status"] == "dynamic":
                label = f"⚡ DYNAMIC {e['disp']} — resolve at runtime"
            elif t is None and e["status"] == "ambiguous":
                c = e["cands"]
                label = f"⚠ AMBIGUOUS {e['disp']} — {len(c)} definitions: " + ", ".join(x.loc for x in c[:4]) + (" …" if len(c) > 4 else "")
            elif t is None:
                label = f"[{e['tag'] or 'ext'}] {e['disp']}(...)"
            else:
                label = ("⇢ " if e["kind"] == "ref" else "") + f"{t.qual}  {t.loc}" + (" ~probable" if e["status"] == "probable" else "")
                if e["tag"]:
                    label = f"[{e['tag']}] " + label
                if e["kind"] == "ref":
                    where += " (passed as reference)"
            suffix = {"recursive": "  ↻ recursive", "seen": "  (expanded above)"}.get(n["note"], "")
            lines.append(f"{prefix}{'└── ' if last else '├── '}{label}   {where}{suffix}")
            if n["children"] or n["hidden"]:
                rec(n["children"], n["hidden"], prefix + ("    " if last else "│   "))
        if hidden:
            lines.append(f"{prefix}└── ({hidden} external/library calls hidden — use --all)")

    rec(tree["children"], tree["hidden"], "")
    return lines


def _mm(text, n=60):
    """Make text safe inside a quoted Mermaid label."""
    t = str(text)
    t = t if len(t) <= n else t[: n - 1] + "…"
    return t.replace("&", "#amp;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


MERMAID_CLASSES = [
    "classDef entry fill:#EEEDFE,stroke:#534AB7,color:#26215C",
    "classDef fn fill:#F1EFE8,stroke:#888780,color:#2C2C2A",
    "classDef llm fill:#FBEAF0,stroke:#993556,color:#4B1528",
    "classDef tool fill:#E1F5EE,stroke:#0F6E56,color:#04342C",
    "classDef io fill:#E6F1FB,stroke:#185FA5,color:#042C53",
    "classDef dyn fill:#FAEEDA,stroke:#854F0B,color:#412402,stroke-dasharray:4 3",
    "classDef amb fill:#FCEBEB,stroke:#A32D2D,color:#501313,stroke-dasharray:4 3",
]


def render_flow_mermaid(tree, idx=None):
    ids, decl, edges, cls = {}, [], [], defaultdict(list)

    def node(key, label, klass):
        if key not in ids:
            ids[key] = f"n{len(ids)}"
            decl.append(f'  {ids[key]}["{label}"]')
            cls[klass].append(ids[key])
        return ids[key]

    def sym_label(s):
        return f"{_mm(s.qual)}<br/>{_mm(s.loc)}"

    def klass_for(e):
        t = e["target"]
        if t is not None and idx is not None:
            r = idx.role_of(t)
            if r in ("llm", "tool"):
                return r
            if r == "retrieval":
                return "io"
        return {"LLM": "llm", "TOOL": "tool", "INVOKE": "llm", "IO": "io"}.get(e["tag"] or "", "fn")

    root = node(tree["sym"].qual, sym_label(tree["sym"]), "entry")

    def rec(pid, nodes):
        for n in nodes:
            e, t = n["edge"], n["edge"]["target"]
            if t is not None:
                cid = node(t.qual, sym_label(t), klass_for(e))
            elif e["status"] == "dynamic":
                cid = node(("dyn", pid, e["disp"]), "⚡ " + _mm(e["disp"], 40) + "<br/>chosen at runtime", "dyn")
            elif e["status"] == "ambiguous":
                cid = node(("amb", e["disp"]), "⚠ " + _mm(e["disp"], 40) + f"<br/>{len(e['cands'])} possible definitions", "amb")
            else:
                cid = node(("ext", e["disp"]), f"{e['tag'] or 'lib'}: {_mm(e['disp'], 40)}", klass_for(e))
            arrow = ' -. "callback" .-> ' if e["kind"] == "ref" else " --> "
            edge = f"  {pid}{arrow}{cid}"
            if edge not in edges:
                edges.append(edge)
            rec(cid, n["children"])

    rec(root, tree["children"])
    out = ["flowchart TD"] + decl + edges + ["  " + c for c in MERMAID_CLASSES]
    out += [f"  class {','.join(v)} {k}" for k, v in cls.items()]
    return out


def resolve_target(idx, target):
    targets = idx.find_targets(target)
    if not targets:
        print(f"No definition found for '{target}'. Try `gt.py callers {target.split('.')[-1]}` or `rg -n {target.split('.')[-1]}`.")
        return None
    if len(targets) > 1:
        print(f"'{target}' is defined {len(targets)} times — pick one with file:func:")
        for s in targets:
            print(f"  {s.file}:{s.qual}    ({s.loc})")
        return None
    return targets[0]


def cmd_flow(args):
    root = get_root(args)
    idx = Index(root).build()
    start = resolve_target(idx, args.target)
    if start is None:
        return 2
    tree, stats = flow_tree(idx, start, args.depth, args.all)
    if args.mermaid:
        text = "```mermaid\n" + "\n".join(render_flow_mermaid(tree, idx)) + "\n```"
        print(text)
        if stats.get("ambiguous") or stats.get("dynamic"):
            print("\n⚡/⚠ boxes are decided at runtime — confirm them with a trace before documenting.")
    else:
        head = [f"FLOW from {start.qual}  ({start.loc})   depth={args.depth}",
                "Static, name-based. ⇢ = function passed as callback/tool/node · ~probable = guessed by name · "
                "⚠/⚡ = confirm at runtime.", ""]
        tail = ["", "Summary: " + ", ".join(f"{v} {k}" for k, v in stats.items()) if stats else ""]
        if stats.get("ambiguous") or stats.get("dynamic"):
            tail.append("Next: resolve ⚠/⚡ with a breakpoint, a temporary log, or @trace + `gt.py trace view latest`.")
        body = "\n".join(head + render_flow_text(tree) + tail)
        text = f"```text\n{body}\n```"
        print(body)
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(text + "\n", encoding="utf-8")
        print(f"\n(written to {args.md})")
    return 0


# --------------------------------------------------------------------------- callers


def cmd_callers(args):
    root = get_root(args)
    idx = Index(root).build().load_text()
    name = args.name.split(".")[-1]
    defs = [s for s in idx.by_name.get(name, []) if args.name == name or s.qual.endswith(args.name)]
    print(f"CALLERS of `{args.name}`")
    print("  defined at: " + (", ".join(f"{s.qual} {s.loc}" for s in defs) if defs else "— no definition in repo (external, dynamic, or hallucinated)"))
    print()
    hits = []
    seen_lines = set()
    for s in idx.syms:
        for kind, short, disp, ln in s.calls:
            if short != name or kind == "base":
                continue
            if args.name != name and not disp.endswith(args.name.split(".", 1)[-1]) and not disp.startswith(("self.", "cls.")):
                continue
            key = (s.file, ln)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            fl = idx.file_lines.get(s.file, [])
            code = fl[ln - 1].strip() if 0 < ln <= len(fl) else ""
            where = "" if s.kind == "module" else s.qual
            hits.append((s.file, ln, where, kind, code))
    word = re.compile(r"\b" + re.escape(name) + r"\b")
    quoted = re.compile(r"['\"]" + re.escape(name) + r"['\"]")
    imp_re = re.compile(r"^\s*(?:from\s+\S+\s+)?import\s.*\b" + re.escape(name) + r"\b")
    for rel, lines in idx.file_lines.items():
        lang = LANG_BY_EXT.get(Path(rel).suffix.lower())
        for i, line in enumerate(lines, 1):
            if (rel, i) in seen_lines:
                continue
            is_def = any(d.file == rel and d.line == i for d in defs)
            if lang != "py" and not is_def and re.search(r"\b" + re.escape(name) + r"\s*\(", line):
                hits.append((rel, i, "", "call?", line.strip()))
            elif lang != "py" and not is_def and word.search(line) and not is_comment(line):
                hits.append((rel, i, "", "ref?", line.strip()))
            elif quoted.search(line):
                hits.append((rel, i, "", "string", line.strip()))
            elif lang == "py" and imp_re.search(line):
                hits.append((rel, i, "", "import", line.strip()))
    for rel in idx.config_files:
        for i, line in enumerate(read_text(root / rel).splitlines(), 1):
            if word.search(line):
                hits.append((rel, i, "", "config", line.strip()))
    if not hits:
        print("  0 references found.")
        if defs:
            print("  → Possibly dead code. Before deleting, check dynamic dispatch in docs/CODEMAP.md and run the tests.")
        return 0
    hits.sort()
    real = [h for h in hits if h[3] != "import"]
    w_loc = max(len(f"{h[0]}:{h[1]}") for h in hits) + 2
    w_in = max([len(h[2]) + 3 for h in hits] + [0]) + 1
    for rel, ln, qual, kind, code in hits:
        loc = f"{rel}:{ln}"
        print(f"  {loc:<{w_loc}}{('in ' + qual) if qual else '':<{w_in}}[{kind:<6}] {code[:90]}")
    if not real and defs:
        print("\n  → Only imported, never used: possibly dead code (or used dynamically — check CODEMAP).")
    files = len({h[0] for h in hits})
    print(f"\n{len(hits)} references in {files} files.  [call]=direct call · [ref]=passed as value (callback/tool/node) · "
          "[string]=referenced by name (dynamic) · [config]=mentioned in config")
    return 0


# --------------------------------------------------------------------------- verify

CITE_RE = re.compile(
    r"(?<![\w/.:-])(?P<path>(?:[A-Za-z]:)?(?:[\w.\-]+[/\\])*[\w\-.]*[\w\-]\.[A-Za-z][A-Za-z0-9]{0,6})"
    r"(?:(?::|#L|,?\s+(?:line|lines|L)\s*)(?P<l1>\d+)(?:\s*(?:-|–|to)\s*L?(?P<l2>\d+))?)"
)
BARE_PATH_RE = re.compile(r"`(?P<path>[\w.\-/\\]+\.[A-Za-z][A-Za-z0-9]{0,6})`")
TICK_RE = re.compile(r"(?<!`)`([^`\n]{1,120})`(?!`)")
IDENT_RE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")
FENCE_RE = re.compile(r"^```(\w*)\s*$")


def _all_files(root: Path):
    return [rel_of(root, p) for p in walk_files(root, TEXT_EXTS | {""})]


def cmd_verify(args):
    root = get_root(args)
    text = sys.stdin.read() if args.file == "-" else read_text(Path(args.file))
    if not text.strip():
        print("Nothing to verify (empty input).")
        return 2
    idx = Index(root).build().load_text()
    files = _all_files(root)
    fileset = set(files)
    ok = warn = bad = info = 0
    out_c, out_s, out_b = [], [], []

    def mark(level):
        nonlocal ok, warn, bad, info
        if level == "ok":
            ok += 1; return "✅"
        if level == "warn":
            warn += 1; return "⚠️ "
        if level == "bad":
            bad += 1; return "❌"
        info += 1; return "ℹ️ "

    def resolve_path(p):
        p = p.replace("\\", "/").lstrip("./") if not p.startswith("../") else p
        ap = Path(p)
        if ap.is_absolute():
            p = rel_of(root, ap)
        if p in fileset or (root / p).is_file():
            return "exact", [p]
        suffix = [f for f in files if f.endswith("/" + p)]
        if suffix:
            return "suffix", suffix
        base = Path(p).name
        same_name = [f for f in files if Path(f).name == base]
        return "missing", same_name

    def lines_of(rel):
        if rel not in idx.file_lines:
            idx.file_lines[rel] = read_text(root / rel).splitlines()
        return idx.file_lines[rel]

    # split prose and fenced code
    prose_lines, blocks, cur, lang = [], [], None, ""
    for ln in text.splitlines():
        m = FENCE_RE.match(ln.strip())
        if m and cur is None:
            cur, lang = [], m.group(1)
            continue
        if ln.strip().startswith("```") and cur is not None:
            if lang == "mermaid":      # diagrams: check their file:line labels like prose
                prose_lines.extend(re.sub(r"<[^>]+>", " ", x) for x in cur)
            else:
                blocks.append((lang, cur))
            cur = None
            continue
        if cur is not None:
            cur.append(ln)
        else:
            prose_lines.append(ln)

    seen_c, seen_s = set(), set()
    for line in prose_lines:
        syms_here = []
        for t in TICK_RE.findall(line):
            t2 = re.sub(r"\(.*\)$", "", t.strip())
            t2 = re.sub(r"^(?:self|cls|this)\.", "", t2)
            if IDENT_RE.match(t2):
                syms_here.append(t2)
        # citations
        cited_paths = set()
        for m in CITE_RE.finditer(line):
            path, l1, l2 = m.group("path"), int(m.group("l1")), int(m.group("l2") or m.group("l1"))
            if "://" in line[max(0, m.start() - 8):m.start() + 3]:
                continue
            if Path(path).suffix.lower() not in TEXT_EXTS and "/" not in path and not (root / path).exists():
                continue  # e.g. example.com:8080
            cited_paths.add(path)
            key = (path, l1, l2)
            if key in seen_c:
                continue
            seen_c.add(key)
            how, found = resolve_path(path)
            label = f"{path}:{l1}" + (f"-{l2}" if l2 != l1 else "")
            if how == "missing":
                hint = f" (files with that name: {', '.join(found[:3])})" if found else ""
                out_c.append(f"  {mark('bad')} {label:<34} file not found in repo{hint}")
                continue
            if len(found) > 1:
                out_c.append(f"  {mark('warn')} {label:<34} ambiguous path — matches {', '.join(found[:4])}")
                continue
            rel = found[0]
            fl = lines_of(rel)
            if l1 < 1 or l2 > len(fl) or l1 > l2:
                out_c.append(f"  {mark('bad')} {label:<34} line out of range — {rel} has {len(fl)} lines")
                continue
            prefix = "" if how == "exact" else f"(resolved to {rel}) "
            names = [x.split(".")[-1] for x in syms_here]
            names = [n for n in names if n not in COMMON_WORDS and len(n) > 2 and n != Path(rel).stem
                     and ("." + n.lower()) not in TEXT_EXTS]
            near = ""
            if names:
                def_rx = [re.compile(r"(?:def|class|function|func|fn|fun|const|let|var|type|interface)\s+(?:\([^)]*\)\s*)?"
                                     + re.escape(n) + r"\b|^\s*" + re.escape(n) + r"\s*=") for n in names]
                in_range = "\n".join(fl[l1 - 1:l2])
                def_near = [k for k in range(max(1, l1 - 2), min(len(fl), l2 + 2) + 1)
                            if any(rx.search(fl[k - 1]) for rx in def_rx)]
                if any(re.search(r"\b" + re.escape(n) + r"\b", in_range) for n in names):
                    pass
                elif def_near:
                    k = def_near[0]
                    near = f"  (off by {l1 - k if k < l1 else k - l2}: defined at L{k})"
                else:
                    where = []
                    for n, rx in zip(names[:3], def_rx[:3]):
                        for k, txt in enumerate(fl, 1):
                            if rx.search(txt):
                                where.append(f"`{n}` is defined at {rel}:{k}")
                                break
                    hint = ("; " + "; ".join(where)) if where else f"; {', '.join('`' + n + '`' for n in names[:3])} not near these lines"
                    out_c.append(f"  {mark('warn')} {label:<34} {prefix}cited lines don't mention {names[0]!r}{hint}")
                    continue
            shown = fl[l1 - 1].strip()[:70] or "(blank line)"
            if how == "suffix":
                out_c.append(f"  {mark('warn')} {label:<34} {prefix}write the full path · L{l1}: {shown}{near}")
            else:
                out_c.append(f"  {mark('ok')} {label:<34} L{l1}: {shown}{near}")
        # bare paths in backticks
        for m in BARE_PATH_RE.finditer(line):
            path = m.group("path")
            if path in cited_paths or ("path", path) in seen_c or Path(path).suffix.lower() not in TEXT_EXTS:
                continue
            seen_c.add(("path", path))
            how, found = resolve_path(path)
            if how == "exact":
                out_c.append(f"  {mark('ok')} {path:<34} exists")
            elif how == "suffix" and len(found) == 1:
                out_c.append(f"  {mark('warn')} {path:<34} exists as {found[0]} (use the full path)")
            elif how == "suffix":
                out_c.append(f"  {mark('warn')} {path:<34} ambiguous — {', '.join(found[:4])}")
            else:
                out_c.append(f"  {mark('bad')} {path:<34} file not found in repo")
        # symbols
        for s in syms_here:
            if s in seen_s:
                continue
            seen_s.add(s)
            last = s.split(".")[-1]
            first = s.split(".")[0]
            if (Path(s).suffix.lower() in TEXT_EXTS and "." in s) or keyword.iskeyword(s) or \
                    s.lower() in COMMON_WORDS or len(last) < 3 or (s in BUILTIN_NAMES and "." not in s):
                continue
            pad = " " * max(1, 30 - len(s))
            defs = [d for d in idx.by_name.get(last, []) if d.kind != "module"]
            stdlib = IDENT_RE.match(first) is not None and is_stdlib(first)
            if "." in s:
                exact = [d for d in defs if d.qual == s or d.qual.endswith("." + s)]
                in_mod = [d for d in defs if modpath_of(d.file).split(".")[-1] == first or
                          modpath_of(d.file).endswith("." + ".".join(s.split(".")[:-1]))]
                if exact or in_mod:
                    hit = exact or in_mod
                    where = ", ".join(d.loc for d in hit[:2])
                    out_s.append(f"  {mark('ok')} `{s}`{pad}defined at {where}")
                elif first in idx.imported_names or stdlib:
                    out_s.append(f"  {mark('info')} `{s}`{pad}external library — not checked here; confirm against the installed version")
                elif first[:1].isupper() and first in idx.by_name:
                    where = ", ".join(f"{d.qual} {d.loc}" for d in defs[:2]) or "no definition at all"
                    out_s.append(f"  {mark('warn' if defs else 'bad')} `{s}`{pad}`{first}` exists but has no `{last}` — found: {where}")
                elif first in idx.idents and (defs or last in idx.idents):
                    out_s.append(f"  {mark('ok')} `{s}`{pad}`{first}` and `{last}` both appear in code (attribute access; type not checked)")
                elif first not in idx.idents:
                    out_s.append(f"  {mark('bad')} `{s}`{pad}`{first}` is not imported, defined or used anywhere in this repo — likely hallucinated")
                else:
                    out_s.append(f"  {mark('bad')} `{s}`{pad}`{last}` not found anywhere in repo — likely hallucinated")
            elif defs:
                where = ", ".join(d.loc for d in defs[:2]) + (f" (+{len(defs) - 2} more)" if len(defs) > 2 else "")
                out_s.append(f"  {mark('ok')} `{s}`{pad}defined at {where}")
            elif last in idx.idents:
                out_s.append(f"  {mark('ok')} `{s}`{pad}appears in code/config (not a definition)")
            elif stdlib:
                out_s.append(f"  {mark('info')} `{s}`{pad}standard library module")
            else:
                out_s.append(f"  {mark('bad')} `{s}`{pad}not found anywhere in repo — likely hallucinated")
    # code blocks
    for i, (lang, body) in enumerate(blocks, 1):
        cand = [" ".join(l.split()) for l in body]
        cand = [c for c in cand if len(c) > 12 and not c.startswith(("#", "//", "$", ">>>", "python ", "pip ", "npm "))]
        if not cand or lang in ("bash", "sh", "shell", "console", "text", "json", "yaml", "md", "markdown"):
            continue
        hit = sum(1 for c in cand if c in idx.norm_lines)
        tag = f"block {i} ({lang or 'code'}, {len(cand)} lines)"
        if hit == len(cand):
            out_b.append(f"  {mark('ok')} {tag}: all {hit} lines found verbatim in repo")
        elif hit:
            missing = [c for c in cand if c not in idx.norm_lines][:2]
            out_b.append(f"  {mark('warn')} {tag}: only {hit}/{len(cand)} lines match the repo — if presented as existing code it was altered; "
                         f"e.g. not found: {missing[0][:60]!r}")
        else:
            out_b.append(f"  {mark('info')} {tag}: not in repo — fine if this is NEW code being proposed, wrong if quoted as existing")

    print(f"groundtruth verify — {args.file}  (repo: {root})")
    for title, rows in (("Citations & paths", out_c), ("Symbols", out_s), ("Code blocks", out_b)):
        if rows:
            print(f"\n{title}")
            print("\n".join(rows))
    total = ok + warn + bad
    print(f"\nResult: {ok} ✅  {warn} ⚠️  {bad} ❌  ({info} info)")
    if total == 0:
        print("No file:line citations or `symbols` found — an answer about this code should cite evidence.")
        return 1
    if bad:
        print("→ Fix every ❌ before trusting or sending this answer (re-open the file, search again, or mark it unknown).")
        return 1
    if warn:
        print("→ Re-check the ⚠️ items.")
    else:
        print("→ All references are real. (Real references ≠ correct reasoning: still check [INFERRED] claims.)")
    return 0


# --------------------------------------------------------------------------- viz


def build_viz_data(idx, root: Path, max_nodes=20000, max_runs=30):
    """Everything the HTML report needs, as plain JSON-able data."""
    syms = [s for s in idx.syms if s.kind != "module" or s.calls]   # module-level code = registries, graph wiring
    total_syms = len(syms)
    if len(syms) > max_nodes:  # huge repo: keep what is reachable from entry points and AI hotspots
        keep, frontier = set(), []
        for loc, _, _ in idx.entries:
            f, _, ln = loc.rpartition(":")
            frontier += [s for s in idx.syms if s.file == f and s.line == int(ln)]
        frontier += [s for s in syms if idx.role_of(s)]
        while frontier and len(keep) < max_nodes:
            s = frontier.pop(0)
            if id(s) in keep:
                continue
            keep.add(id(s))
            _, es, _ = edges_of(idx, s)
            frontier += [e["target"] for e in es if e["target"] is not None]
        syms = [s for s in syms if id(s) in keep]
    ids = {id(s): i for i, s in enumerate(syms)}
    by_file = defaultdict(list)
    for s in syms:
        by_file[s.file].append(s)

    def containing(loc):
        f, _, ln = loc.rpartition(":")
        try:
            ln = int(ln)
        except ValueError:
            return -1
        best = None
        for s in by_file.get(f, []):
            if s.line <= ln <= max(s.end, s.line) and (best is None or (s.end - s.line) < (best.end - best.line)):
                best = s
        return ids[id(best)] if best is not None else -1

    nodes = [[s.qual, s.kind, s.file, s.line, idx.role_of(s) or "", (s.doc or "")[:200], (s.decos[0] if s.decos else "")[:90]]
             for s in syms]
    edges, hidden = {}, {}
    for i, s in enumerate(syms):
        if s.lang != "py":
            continue
        _, es, h = edges_of(idx, s)
        rows = []
        for e in es:
            t = ids.get(id(e["target"]), -1) if e["target"] is not None else -1
            k = ("d" if e["status"] == "dynamic" else "a" if e["status"] == "ambiguous"
                 else "x" if t < 0 else "r" if e["kind"] == "ref" else "c")
            rows.append([k, t, e["disp"][:90], e["line"], e["status"], e["tag"] or "",
                         [ids[id(c)] for c in e["cands"] if id(c) in ids][:8]])
        if rows:
            edges[i] = rows
        if h:
            hidden[i] = h
    dup, clones = find_duplicates(idx)

    def group(d, cap):
        return {k: [[loc, txt, containing(loc)] for loc, txt in v[:cap]] + ([["…", f"{len(v) - cap} more", -1]] if len(v) > cap else [])
                for k, v in d.items()}

    runs = []
    tdir = root / ".groundtruth" / "traces"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agent_trace
        budget = 20_000_000
        for p in agent_trace._runs(tdir)[:max_runs]:
            r = agent_trace.Run(p)
            item = {"id": r.id, "name": r.name, "status": r.status, "ms": r.end.get("ms"),
                    "ts": r.info.get("ts") or min([x.get("ts", 0) for x in r.spans.values()] or [0]),
                    "input": r.info.get("input"), "output": r.end.get("output"),
                    "spans": [{k: v for k, v in x.items() if k not in ("t", "run")} for x in r.spans.values()],
                    "events": [{k: v for k, v in x.items() if k not in ("t", "run")} for x in r.events]}
            size = len(json.dumps(item, default=str))
            if size > budget:
                break
            budget -= size
            runs.append(item)
    except Exception as e:  # traces are optional
        print(f"(skipping agent runs: {e})", file=sys.stderr)
    nf = len(idx.code_files)
    return {
        "repo": root.name, "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": {"files": nf, "functions": sum(1 for s in syms if "function" in s.kind or "method" in s.kind),
                  "modules": sum(1 for s in syms if s.kind == "module"),
                  "classes": sum(1 for s in syms if s.kind == "class"), "entries": len(set(idx.entries)),
                  "hotspots": sum(len(v) for v in idx.hot.values()), "dynamic": sum(len(v) for v in idx.dynamic.values()),
                  "dups": len(dup), "clones": len(clones), "runs": len(runs),
                  "run_errors": sum(1 for r in runs if r["status"] == "error"), "truncated": len(syms) < total_syms},
        "entries": [[loc, kind, what, containing(loc)] for loc, kind, what in sorted(set(idx.entries))],
        "hot": group({k: idx.hot[k] for _, k in HOT_PATTERNS if k in idx.hot}, 300),
        "dynamic": group(dict(idx.dynamic), 300),
        "dups": [[n, [[x.qual, x.loc, ids.get(id(x), -1)] for x in v]] for n, v in sorted(dup.items())[:200]],
        "clones": [[[x.qual, x.loc, ids.get(id(x), -1)] for x in g] for g in clones[:200]],
        "parse_errors": [[f"{rel}:{ln}", msg] for rel, ln, msg in idx.parse_errors[:100]],
        "nodes": nodes, "edges": edges, "hidden": hidden, "runs": runs,
    }


def cmd_viz(args):
    root = get_root(args)
    idx = Index(root).build()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import viz  # noqa: E402
    data = build_viz_data(idx, root, max_runs=args.runs)
    out = Path(args.out) if args.out else root / ".groundtruth" / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(viz.build_html(data), encoding="utf-8")
    st = data["stats"]
    print(f"Report written: {out}\n  {st['functions']} functions · {sum(len(v) for v in data['edges'].values())} calls · "
          f"{st['hotspots']} AI hotspots · {st['runs']} agent runs ({st['run_errors']} with errors)\n"
          f"  Open it in any browser (double-click, or VS Code: right-click → Open with Live Preview / Reveal in File Explorer).")
    if args.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
    return 0


# --------------------------------------------------------------------------- trace


def cmd_trace(args, rest):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import agent_trace  # noqa: E402
    root = get_root(args)
    return agent_trace.main(rest, default_dir=root / ".groundtruth" / "traces")


# --------------------------------------------------------------------------- main


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="gt", description="Evidence tools for AI-written codebases.")
    ap.add_argument("--root", help="repo root (default: nearest folder with .git, else cwd)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("map", help="build docs/CODEMAP.md")
    p.add_argument("--out", help="output path (default docs/CODEMAP.md)")
    p = sub.add_parser("flow", help="static call tree from a function")
    p.add_argument("target")
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--all", action="store_true", help="also show library/external calls")
    p.add_argument("--md", help="also write the result to this markdown file")
    p.add_argument("--mermaid", action="store_true", help="output a Mermaid flowchart (renders on GitHub, VS Code, Notion…)")
    p = sub.add_parser("callers", help="who calls / references a name")
    p.add_argument("name")
    p = sub.add_parser("verify", help="check citations/symbols in an AI answer")
    p.add_argument("file", help="answer file, or - for stdin")
    p = sub.add_parser("viz", help="interactive HTML report: overview, flow explorer, agent run timelines")
    p.add_argument("--out", help="output file (default .groundtruth/report.html)")
    p.add_argument("--open", action="store_true", help="open it in your browser")
    p.add_argument("--runs", type=int, default=30, help="how many recent agent runs to include")
    sub.add_parser("trace", help="inspect agent traces: list | view [run] | show run span | diff a b", add_help=False)

    if argv and argv[0] == "trace" or (len(argv) > 2 and argv[0] == "--root" and argv[2] == "trace"):
        i = argv.index("trace")
        ns = ap.parse_args(argv[:i] + ["trace"])
        return cmd_trace(ns, argv[i + 1:])
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    return {"map": cmd_map, "flow": cmd_flow, "callers": cmd_callers, "verify": cmd_verify, "viz": cmd_viz}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
