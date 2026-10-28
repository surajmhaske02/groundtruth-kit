"""
agent_trace — zero-dependency tracing for agentic / LLM code.

Record every step of an agent run (LLM calls, tool calls, graph nodes, decisions) as JSONL,
then read the run as a tree instead of guessing what the model did.

    from agent_trace import trace, run, span, event      # or tools.groundtruth.agent_trace

    @trace(kind="llm")
    def call_model(messages): ...

    @trace(kind="tool")
    async def search_docs(query: str): ...

    with run("support question", input=q):     # optional; a run starts automatically otherwise
        answer = agent(q)

    event("route", next="search")              # record a decision
    with span("rerank", kind="retrieval") as s:
        top = rerank(docs); s.set(output=[d.id for d in top])

Inspect:  python gt.py trace list | view [run|latest] [--full] | show RUN SPAN | diff RUN_A RUN_B
          (or: python agent_trace.py list ...)

Env:  GT_TRACE=0 disables · GT_TRACE_DIR=path · GT_TRACE_MAX_CHARS=4000 (per string)
Secrets: values of args/keys named like api_key/token/secret/password and strings that look like
keys (sk-..., ghp_..., AKIA..., JWTs) are masked before writing.
For production tracing use OpenTelemetry-based tools (Langfuse, Phoenix, LangSmith, ...).
"""
from __future__ import annotations

import contextvars
import dataclasses
import datetime as _dt
import difflib
import functools
import hashlib
import inspect
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

__all__ = ["trace", "run", "span", "event", "main"]

ENABLED = os.environ.get("GT_TRACE", "1").lower() not in ("0", "false", "off", "no")
MAX_CHARS = int(os.environ.get("GT_TRACE_MAX_CHARS", "4000"))
SECRET_KEY_RE = re.compile(r"api[_-]?key|token|secret|passw|authorization|cookie|credential|private[_-]?key", re.I)
SECRET_VAL_RE = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{20,}|xox[bapr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")
_THIS = os.path.abspath(__file__)

_run_var: contextvars.ContextVar = contextvars.ContextVar("gt_run", default=None)
_parent_var: contextvars.ContextVar = contextvars.ContextVar("gt_parent", default=None)
_lock = threading.Lock()
_dir_cache: list = []
_MISSING = object()
try:
    from asyncio import CancelledError as _Cancelled
except Exception:  # pragma: no cover
    class _Cancelled(BaseException):
        pass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


# --------------------------------------------------------------------------- storage


def _root() -> Path:
    cwd = Path.cwd()
    for q in [cwd, *cwd.parents]:
        if (q / ".git").exists():
            return q
    return cwd


def _trace_dir() -> Path:
    if not _dir_cache:
        d = os.environ.get("GT_TRACE_DIR")
        _dir_cache.append(Path(d) if d else _root() / ".groundtruth" / "traces")
    return _dir_cache[0]


def _write(run_id: str, rec: dict):
    try:
        d = _trace_dir()
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with _lock, open(d / f"{run_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:  # tracing must never break the app
        print(f"[agent_trace] could not write trace: {e}", file=sys.stderr)


def _new_id(n=8):
    return uuid.uuid4().hex[:n]


def _rel(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(_root()).as_posix()
    except Exception:
        return path


# --------------------------------------------------------------------------- serialisation


def _clip(s: str) -> str:
    s = SECRET_VAL_RE.sub("***", s)
    return s if len(s) <= MAX_CHARS else s[:MAX_CHARS] + f"…(+{len(s) - MAX_CHARS} chars)"


def _safe(obj, depth=0, key=None):
    if key is not None and SECRET_KEY_RE.search(str(key)):
        return "***"
    if obj is None or isinstance(obj, (bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else str(obj)
    if isinstance(obj, str):
        return _clip(obj)
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    if depth > 6:
        return _clip(repr(obj))
    if isinstance(obj, dict):
        items = list(obj.items())
        out = {str(k): _safe(v, depth + 1, k) for k, v in items[:60]}
        if len(items) > 60:
            out["…"] = f"+{len(items) - 60} keys"
        return out
    if isinstance(obj, (list, tuple, set, frozenset)):
        seq = list(obj)
        out = [_safe(x, depth + 1) for x in seq[:40]]
        if len(seq) > 40:
            out.append(f"…(+{len(seq) - 40} items)")
        return out
    if hasattr(obj, "shape") and hasattr(obj, "dtype"):  # numpy / torch / pandas-like
        return f"<{type(obj).__name__} shape={tuple(getattr(obj, 'shape', ()))} dtype={getattr(obj, 'dtype', '?')}>"
    if hasattr(obj, "shape") and hasattr(obj, "columns"):  # DataFrame
        return f"<DataFrame shape={obj.shape} columns={list(obj.columns)[:20]}>"
    for attr in ("model_dump", "dict", "to_dict"):  # pydantic v2 / v1 / misc SDK objects
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return _safe(fn(), depth + 1)
            except Exception:
                pass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            return _safe(dataclasses.asdict(obj), depth + 1)
        except Exception:
            pass
    if inspect.isgenerator(obj) or inspect.isasyncgen(obj):
        return f"<{type(obj).__name__}>"
    return _clip(repr(obj))


def _args_of(fn, args, kwargs):
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        out = {}
        for k, v in bound.arguments.items():
            if k in ("self", "cls"):
                out[k] = f"<{type(v).__name__ if k == 'self' else getattr(v, '__name__', v)}>"
            else:
                out[k] = v
        return _safe(out)
    except Exception:
        return _safe({"args": list(args), "kwargs": kwargs})


def _err_info(e: BaseException):
    tb = traceback.extract_tb(e.__traceback__)
    user = [f for f in tb if "site-packages" not in f.filename and "dist-packages" not in f.filename
            and os.path.abspath(f.filename) != _THIS]
    fr = (user or tb)[-1] if (user or tb) else None
    return {
        "type": type(e).__name__,
        "msg": _clip(str(e)),
        "where": f"{_rel(fr.filename)}:{fr.lineno}" if fr else None,
        "code": (fr.line or "").strip() if fr else None,
        "tb": _clip("".join(traceback.format_exception(type(e), e, e.__traceback__))[-3000:]),
    }


# --------------------------------------------------------------------------- runs & spans


class run:
    """Group everything that happens for one request/task. Usable as `with` or `async with`."""

    def __init__(self, name: str = "run", input=None, **meta):
        self.name, self.input, self.meta = name, input, meta
        self.id = None
        self._output = _MISSING
        self._tok = self._ptok = None
        self._t0 = 0.0

    def set(self, output=_MISSING, **meta):
        if output is not _MISSING:
            self._output = output
        self.meta.update(meta)

    def __enter__(self):
        if not ENABLED:
            return self
        self.id = f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{_new_id(6)}"
        self._t0 = time.time()
        self._tok = _run_var.set(self.id)
        self._ptok = _parent_var.set(None)
        _write(self.id, {"t": "run_start", "run": self.id, "name": self.name, "ts": self._t0,
                         "input": _safe(self.input), "meta": _safe({**self.meta, "pid": os.getpid(),
                                                                    "argv": sys.argv[:6]})})
        return self

    def __exit__(self, et, ev, tb):
        if not ENABLED or self.id is None:
            return False
        t1 = time.time()
        rec = {"t": "run_end", "run": self.id, "ts": t1, "ms": round((t1 - self._t0) * 1000, 1),
               "status": "error" if ev else "ok"}
        if self._output is not _MISSING:
            rec["output"] = _safe(self._output)
        if ev:
            rec["error"] = _err_info(ev)
        _write(self.id, rec)
        if self._tok is not None:
            try:
                _parent_var.reset(self._ptok)
                _run_var.reset(self._tok)
            except ValueError:
                _parent_var.set(None)
                _run_var.set(None)
            self._tok = self._ptok = None
        return False

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, et, ev, tb):
        return self.__exit__(et, ev, tb)


class span:
    """Trace a block of code: `with span("retrieve", kind="retrieval", query=q) as s: ...; s.set(output=x)`."""

    def __init__(self, name: str, kind: str = "step", input=None, src: str | None = None, **attrs):
        self.name, self.kind, self.input, self.attrs = name, kind, input, attrs
        self.src = src
        self.id = None
        self._output = _MISSING
        self._implicit_run = None
        self._tok = None
        self._t0 = 0.0
        self.run_id = None
        self.parent = None

    def set(self, output=_MISSING, **attrs):
        if output is not _MISSING:
            self._output = output
        self.attrs.update(attrs)

    def __enter__(self):
        if not ENABLED:
            return self
        if _run_var.get() is None:
            self._implicit_run = run(self.name, input=self.input, implicit=True)
            self._implicit_run.__enter__()
        if self.src is None:
            fr = inspect.currentframe()
            fr = fr.f_back if fr else None
            while fr and os.path.abspath(fr.f_code.co_filename) == _THIS:
                fr = fr.f_back
            if fr:
                self.src = f"{_rel(fr.f_code.co_filename)}:{fr.f_lineno}"
        self.run_id = _run_var.get()
        self.parent = _parent_var.get()
        self.id = _new_id()
        self._t0 = time.time()
        self._tok = _parent_var.set(self.id)
        _write(self.run_id, {"t": "start", "run": self.run_id, "id": self.id, "parent": self.parent,
                             "name": self.name, "kind": self.kind, "ts": self._t0, "src": self.src})
        return self

    def __exit__(self, et, ev, tb):
        self._end(ev)
        return False

    def _end(self, ev):
        if not ENABLED or self.id is None:
            return
        if isinstance(ev, GeneratorExit):  # consumer stopped a stream early: not a failure
            ev = None
        t1 = time.time()
        rec = {"t": "end", "run": self.run_id, "id": self.id, "parent": self.parent, "name": self.name,
               "kind": self.kind, "ts": self._t0, "ts_end": t1, "ms": round((t1 - self._t0) * 1000, 1),
               "status": "error" if ev else "ok", "src": self.src, "input": _safe(self.input)}
        if self._output is not _MISSING:
            rec["output"] = _safe(self._output)
        if self.attrs:
            rec["attrs"] = _safe(self.attrs)
        if ev:
            rec["error"] = _err_info(ev)
        _write(self.run_id, rec)
        if self._tok is not None:
            try:
                _parent_var.reset(self._tok)
            except ValueError:  # exited in a different context
                _parent_var.set(self.parent)
            self._tok = None
        if self._implicit_run:
            if self._output is not _MISSING:
                self._implicit_run.set(output=self._output)
            self._implicit_run.__exit__(type(ev) if ev else None, ev, None)
            self._implicit_run = None

    # -- generators/streams: never leave this span "current" while the stream is suspended
    def _detach(self):
        if self._tok is not None:
            try:
                _parent_var.reset(self._tok)
            except ValueError:
                pass
            self._tok = None
        r = self._implicit_run
        if r is not None and r._tok is not None:
            try:
                _parent_var.reset(r._ptok)
                _run_var.reset(r._tok)
            except ValueError:
                pass
            r._tok = r._ptok = None

    def _attach(self):
        return _run_var.set(self.run_id), _parent_var.set(self.id)

    @staticmethod
    def _release(toks):
        try:
            _parent_var.reset(toks[1])
            _run_var.reset(toks[0])
        except ValueError:
            pass

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, et, ev, tb):
        return self.__exit__(et, ev, tb)


def event(name: str, **data):
    """Record a point-in-time fact under the current step (routing decision, counts, chosen tool...)."""
    if not ENABLED:
        return
    rid = _run_var.get()
    implicit = None
    if rid is None:
        implicit = run(name, implicit=True).__enter__()
        rid = implicit.id
    fr = inspect.currentframe()
    fr = fr.f_back if fr else None
    _write(rid, {"t": "event", "run": rid, "id": _new_id(), "parent": _parent_var.get(), "name": name,
                 "ts": time.time(), "data": _safe(data),
                 "src": f"{_rel(fr.f_code.co_filename)}:{fr.f_lineno}" if fr else None})
    if implicit:
        implicit.__exit__(None, None, None)


def trace(_fn=None, *, kind: str = "step", name: str | None = None, capture_args: bool = True,
          capture_output: bool = True):
    """Decorator. kind: llm | tool | node | retrieval | step | anything you like."""

    def deco(fn):
        label = name or getattr(fn, "__qualname__", getattr(fn, "__name__", "fn"))
        try:
            line = fn.__code__.co_firstlineno
            try:  # skip decorator lines so the location points at `def`
                lines, start = inspect.getsourcelines(fn)
                for k, txt in enumerate(lines):
                    if txt.lstrip().startswith(("def ", "async def ")):
                        line = start + k
                        break
            except (OSError, TypeError):
                pass
            src = f"{_rel(inspect.getsourcefile(fn) or '?')}:{line}"
        except Exception:
            src = None

        def mk(args, kwargs):
            return span(label, kind=kind, input=_args_of(fn, args, kwargs) if capture_args else None, src=src)

        if inspect.isasyncgenfunction(fn):
            @functools.wraps(fn)
            async def agen_wrapper(*args, **kwargs):
                s = mk(args, kwargs).__enter__()
                s._detach()
                it = fn(*args, **kwargs)
                chunks, err = [], None
                try:
                    while True:
                        toks = s._attach()
                        try:
                            item = await it.__anext__()
                        except StopAsyncIteration:
                            break
                        finally:
                            span._release(toks)
                        if len(chunks) < 200:
                            chunks.append(item)
                        try:
                            yield item
                        except (GeneratorExit, _Cancelled):
                            s.set(stopped_early=True)
                            await it.aclose()
                            return
                except BaseException as e:
                    err = e
                    raise
                finally:
                    if capture_output:
                        s.set(output=_stream_summary(chunks))
                    s._end(err)
            return agen_wrapper
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                async with mk(args, kwargs) as s:
                    out = await fn(*args, **kwargs)
                    if capture_output:
                        s.set(output=out)
                    return out
            return async_wrapper
        if inspect.isgeneratorfunction(fn):
            @functools.wraps(fn)
            def gen_wrapper(*args, **kwargs):
                s = mk(args, kwargs).__enter__()
                s._detach()
                it = fn(*args, **kwargs)
                chunks, err = [], None
                try:
                    while True:
                        toks = s._attach()
                        try:
                            item = next(it)
                        except StopIteration:
                            break
                        finally:
                            span._release(toks)
                        if len(chunks) < 200:
                            chunks.append(item)
                        try:
                            yield item
                        except GeneratorExit:
                            s.set(stopped_early=True)
                            it.close()
                            return
                except BaseException as e:
                    err = e
                    raise
                finally:
                    if capture_output:
                        s.set(output=_stream_summary(chunks))
                    s._end(err)
            return gen_wrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with mk(args, kwargs) as s:
                out = fn(*args, **kwargs)
                if capture_output:
                    s.set(output=out)
                return out
        return wrapper

    if not ENABLED:
        return (lambda f: f) if _fn is None else _fn
    return deco(_fn) if callable(_fn) else deco


def _stream_summary(chunks):
    if chunks and all(isinstance(c, str) for c in chunks):
        return {"stream_chunks": len(chunks), "text": "".join(chunks)}
    return {"stream_chunks": len(chunks), "first": chunks[:3]}


# --------------------------------------------------------------------------- reading traces


def _fmt_ms(ms):
    if ms is None:
        return "?"
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.2f}s"


def _runs(d: Path):
    return sorted(d.glob("*.jsonl"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True) if d.exists() else []


def _find_run(d: Path, ref: str):
    runs = _runs(d)
    if not runs:
        raise SystemExit(f"No traces in {d}. Add @trace to your functions and run the flow once.")
    m = re.fullmatch(r"(?:latest|last)(?:~(\d+))?|prev", ref)
    if m:
        i = 1 if ref == "prev" else int(m.group(1) or 0)
        if i >= len(runs):
            raise SystemExit(f"Only {len(runs)} runs recorded.")
        return runs[i]
    hits = [p for p in runs if p.stem.startswith(ref) or ref in p.stem]
    if len(hits) != 1:
        raise SystemExit(f"Run '{ref}' {'not found' if not hits else 'is ambiguous: ' + ', '.join(p.stem for p in hits[:5])}")
    return hits[0]


class Run:
    def __init__(self, path: Path):
        self.path, self.id = path, path.stem
        self.info, self.end = {}, {}
        self.spans: dict[str, dict] = {}
        self.events: list[dict] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = r.get("t")
            if t == "run_start":
                self.info = r
            elif t == "run_end":
                self.end = r
            elif t == "start":
                self.spans.setdefault(r["id"], {}).update({**r, "status": "unfinished"})
            elif t == "end":
                self.spans.setdefault(r["id"], {}).update(r)
            elif t == "event":
                self.events.append(r)
        self.children: dict = {}
        for node in list(self.spans.values()) + [dict(e, kind="event") for e in self.events]:
            self.children.setdefault(node.get("parent"), []).append(node)
        for kids in self.children.values():
            kids.sort(key=lambda n: n.get("ts", 0))

    @property
    def name(self):
        return self.info.get("name", "?")

    @property
    def status(self):
        if any(s.get("status") == "error" for s in self.spans.values()) or self.end.get("status") == "error":
            return "error"
        if not self.end or any(s.get("status") == "unfinished" for s in self.spans.values()):
            return "unfinished"
        return "ok"

    def flat(self):
        """Depth-first list of (depth, node) in execution order."""
        out = []

        def rec(pid, depth):
            for n in self.children.get(pid, []):
                out.append((depth, n))
                if n.get("kind") != "event":
                    rec(n["id"], depth + 1)
        rec(None, 0)
        return out


def _preview(v, full=False, width=150):
    if v is None:
        return "None"
    s = json.dumps(v, ensure_ascii=False, default=str, indent=2 if full else None)
    if full:
        return s
    s = " ".join(s.split())
    return s if len(s) <= width else s[: width - 1] + "…"


ICON = {"ok": "✓", "error": "✗", "unfinished": "⏳"}


def cmd_list(d, n):
    runs = _runs(d)[:n]
    if not runs:
        print(f"No traces in {d}.")
        return 0
    print(f"{'RUN ID':<24} {'STATUS':<12} {'STEPS':>5} {'ERR':>4} {'TIME':>8}  NAME")
    for p in runs:
        r = Run(p)
        errs = sum(1 for s in r.spans.values() if s.get("status") == "error")
        ms = r.end.get("ms")
        print(f"{r.id:<24} {ICON[r.status] + ' ' + r.status:<12} {len(r.spans):>5} {errs:>4} {_fmt_ms(ms):>8}  {r.name}")
    print(f"\n{d}")
    return 0


def cmd_view(d, ref, full=False, errors_only=False, mermaid=False):
    r = Run(_find_run(d, ref))
    if mermaid:
        print("```mermaid\n" + "\n".join(render_sequence(r)) + "\n```")
        return 0
    errs = [s for s in r.spans.values() if s.get("status") == "error"]
    print(f"RUN {r.id}  \"{r.name}\"  {ICON[r.status]} {r.status.upper()}  {_fmt_ms(r.end.get('ms'))}  "
          f"({len(r.spans)} steps, {len(errs)} errors, {len(r.events)} events)")
    if r.info.get("input") is not None:
        print(f"input : {_preview(r.info.get('input'), full)}")
    if "output" in r.end:
        print(f"output: {_preview(r.end.get('output'), full)}")
    print()
    flat = r.flat()
    if errors_only:
        bad_ids = set()
        for s in errs:
            cur = s
            while cur:
                bad_ids.add(cur.get("id"))
                cur = r.spans.get(cur.get("parent"))
        flat = [(dep, n) for dep, n in flat if n.get("id") in bad_ids]
    for i, (depth, n) in enumerate(flat):
        pad = "│  " * depth
        if n.get("kind") == "event":
            print(f"{pad}• {n['name']}  {_preview(n.get('data'), full, 120)}")
            continue
        st = n.get("status")
        head = f"{pad}[{n.get('kind')}] {n.get('name')}  {_fmt_ms(n.get('ms'))}"
        if st == "error":
            e = n.get("error") or {}
            head += f"  ✗ {e.get('type')}: {e.get('msg', '')[:100]}  at {e.get('where')}"
        elif st == "unfinished":
            head += "  ⏳ did not finish (crash, hang, timeout or still running)"
        else:
            head += f"  {n.get('src') or ''}"
        print(head)
        if n.get("input") is not None:
            print(f"{pad}     in : {_preview(n.get('input'), full)}")
        if "output" in n:
            print(f"{pad}     out: {_preview(n.get('output'), full)}")
        if n.get("attrs"):
            print(f"{pad}     attr: {_preview(n.get('attrs'), full)}")
    first_err = min(errs, key=lambda s: s.get("ts", 0)) if errs else None
    if first_err:
        # deepest error in the earliest failing chain = closest to the cause
        kids = [s for s in errs if s.get("parent") == first_err.get("id")]
        while kids:
            first_err = min(kids, key=lambda s: s.get("ts", 0))
            kids = [s for s in errs if s.get("parent") == first_err.get("id")]
        e = first_err.get("error") or {}
        print(f"\nFIRST ERROR  [{first_err.get('kind')}] {first_err.get('name')}  defined {first_err.get('src')}")
        print(f"             {e.get('type')}: {e.get('msg', '')[:200]}")
        print(f"             raised at {e.get('where')}: {e.get('code')}")
    print("\nRead top-down. The real bug is usually the FIRST step whose output is wrong for its input,"
          " which can be well before the step that crashed.")
    return 0


def _seq_text(v, n=48):
    if v is None:
        return ""
    if isinstance(v, dict):
        parts = []
        for k, x in v.items():
            if k in ("self", "cls"):
                continue
            xs = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
            parts.append(f"{k}={xs}")
        t = ", ".join(parts)
    else:
        t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    t = " ".join(str(t).split())
    t = t if len(t) <= n else t[: n - 1] + "…"
    for a, b in ((";", ","), ("#", "#35;"), ("<", "#lt;"), (">", "#gt;"), ("%%", "%")):
        t = t.replace(a, b)
    return t


def render_sequence(r: "Run", limit=150):
    """Mermaid sequence diagram of one run: who called whom, with what, and what came back."""
    names, out, count = {}, ["sequenceDiagram", "  autonumber", "  participant U as caller"], [0]

    def pid(n):
        key = n.get("name")
        if key not in names:
            names[key] = f"p{len(names) + 1}"
            label = _seq_text(f"{key} ({n.get('kind')})", 40).replace(":", " ")
            out.append(f"  participant {names[key]} as {label}")
        return names[key]

    def rec(parent_id, parent_pid):
        for n in r.children.get(parent_id, []):
            if count[0] >= limit:
                return
            count[0] += 1
            if n.get("kind") == "event":
                out.append(f"  Note over {parent_pid}: {_seq_text(n.get('name') + ' ' + _seq_text(n.get('data'), 40), 60)}")
                continue
            me = pid(n)
            out.append(f"  {parent_pid}->>+{me}: {_seq_text(n.get('input')) or n.get('name')}")
            rec(n.get("id"), me)
            st = n.get("status")
            if st == "error":
                e = n.get("error") or {}
                out.append(f"  {me}--x-{parent_pid}: {_seq_text(str(e.get('type')) + ': ' + str(e.get('msg', '')))}")
            elif st == "unfinished":
                out.append(f"  Note over {me}: did not finish")
                out.append(f"  {me}--x-{parent_pid}: (no return)")
            else:
                out.append(f"  {me}-->>-{parent_pid}: {_seq_text(n.get('output')) or 'ok'} ({_fmt_ms(n.get('ms'))})")

    rec(None, "U")
    if count[0] >= limit:
        out.append(f"  Note over U: … truncated after {limit} steps")
    return out


def cmd_show(d, ref, span_ref):
    r = Run(_find_run(d, ref))
    hits = [s for s in list(r.spans.values()) + r.events
            if s.get("id", "").startswith(span_ref) or s.get("name") == span_ref]
    if not hits:
        print(f"No span '{span_ref}' in run {r.id}. Use the name or the id from `trace view`.")
        return 1
    for s in hits:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
    return 0


def _h(v):
    return hashlib.md5(json.dumps(v, sort_keys=True, default=str).encode()).hexdigest()


def cmd_diff(d, a_ref, b_ref):
    A, B = Run(_find_run(d, a_ref)), Run(_find_run(d, b_ref))
    fa = [(dep, n) for dep, n in A.flat()]
    fb = [(dep, n) for dep, n in B.flat()]
    sig = lambda dep, n: f"{dep}|{n.get('kind')}|{n.get('name')}"  # noqa: E731
    sa, sb = [sig(*x) for x in fa], [sig(*x) for x in fb]
    print(f"A = {A.id} \"{A.name}\" {ICON[A.status]} {A.status}   ({len(fa)} steps)")
    print(f"B = {B.id} \"{B.name}\" {ICON[B.status]} {B.status}   ({len(fb)} steps)\n")
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    first_struct, rows, marks = None, [], []   # marks: (depth, differs, detail-or-None)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                (dep, na), (_, nb) = fa[i1 + k], fb[j1 + k]
                val = "data" if na.get("kind") == "event" else "output"
                ea, eb = na.get("error") or {}, nb.get("error") or {}
                same_out = (_h(na.get(val)) == _h(nb.get(val)) and na.get("status") == nb.get("status")
                            and (ea.get("type"), ea.get("msg")) == (eb.get("type"), eb.get("msg")))
                same_in = _h(na.get("input")) == _h(nb.get("input"))
                rows.append(f"  {'=' if same_out else '≠'} {'  ' * dep}[{na.get('kind')}] {na.get('name')}")
                marks.append((dep, not same_out, (na, nb, same_in, val)))
        else:
            if first_struct is None:
                first_struct = (op, [fa[i][1] for i in range(i1, i2)], [fb[j][1] for j in range(j1, j2)])
            for i in range(i1, i2):
                dep, n = fa[i]
                rows.append(f"  - {'  ' * dep}[{n.get('kind')}] {n.get('name')}   (only in A)")
                marks.append((dep, True, None))
            for j in range(j1, j2):
                dep, n = fb[j]
                rows.append(f"  + {'  ' * dep}[{n.get('kind')}] {n.get('name')}   (only in B)")
                marks.append((dep, True, None))
    # earliest differing step with no differing step inside it = where the runs really split
    first_out = None
    for i, (dep, differs, detail) in enumerate(marks):
        if not differs or detail is None:
            continue
        j, inner = i + 1, False
        while j < len(marks) and marks[j][0] > dep:
            if marks[j][1]:
                inner = True
                break
            j += 1
        if not inner:
            first_out = detail
            break
    for row in rows[:80]:
        print(row)
    if len(rows) > 80:
        print(f"  … {len(rows) - 80} more")
    print()
    if first_out:
        na, nb, same_in, val = first_out
        print(f"FIRST DIFFERENT RESULT (innermost): [{na.get('kind')}] {na.get('name')}  ({na.get('src')})")
        print(f"  A {val}: {_preview(na.get(val)) if na.get('status') != 'error' else 'ERROR ' + str((na.get('error') or {}).get('msg'))}")
        print(f"  B {val}: {_preview(nb.get(val)) if nb.get('status') != 'error' else 'ERROR ' + str((nb.get('error') or {}).get('msg'))}")
        if na.get("kind") == "event":
            print("  → A recorded decision differs. Look at the state/inputs that fed this decision.")
        elif same_in:
            print("  → SAME input, DIFFERENT result: nondeterminism inside this step (LLM sampling, external data, time,"
                  " randomness, caching). Pin temperature/seed or record & replay this step.")
        else:
            print(f"  → Inputs differ too:\n     A in: {_preview(na.get('input'))}\n     B in: {_preview(nb.get('input'))}\n"
                  "     The cause is upstream — check the steps before this one.")
    if first_struct:
        op, xa, xb = first_struct
        print(f"\nFIRST DIFFERENT PATH: A ran {[n.get('name') for n in xa][:5] or 'nothing'}, "
              f"B ran {[n.get('name') for n in xb][:5] or 'nothing'}")
        print("  → The agent took a different route here. The decision was made by the step just before"
              " (router / LLM tool choice) — compare its output above.")
    if not first_out and not first_struct:
        print("Runs are identical in structure and recorded outputs.")
    return 0


def main(argv=None, default_dir=None):
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="trace", description="Inspect agent runs recorded by agent_trace.")
    ap.add_argument("--dir", help="trace directory (default .groundtruth/traces at repo root)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list")
    p.add_argument("-n", type=int, default=20)
    p = sub.add_parser("view")
    p.add_argument("run", nargs="?", default="latest", help="run id/prefix, latest, latest~1, prev")
    p.add_argument("--full", action="store_true")
    p.add_argument("--errors", action="store_true", help="only the chain(s) that failed")
    p.add_argument("--mermaid", action="store_true", help="output a Mermaid sequence diagram of the run")
    p = sub.add_parser("show")
    p.add_argument("run")
    p.add_argument("span", help="span id prefix or name")
    p = sub.add_parser("diff")
    p.add_argument("a")
    p.add_argument("b")
    args = ap.parse_args(argv)
    d = Path(args.dir) if args.dir else (Path(default_dir) if default_dir else _trace_dir())
    if args.cmd in (None, "list"):
        return cmd_list(d, getattr(args, "n", 20))
    if args.cmd == "view":
        return cmd_view(d, args.run, args.full, args.errors, args.mermaid)
    if args.cmd == "show":
        return cmd_show(d, args.run, args.span)
    if args.cmd == "diff":
        return cmd_diff(d, args.a, args.b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
