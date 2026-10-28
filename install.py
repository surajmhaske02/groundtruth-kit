#!/usr/bin/env python3
"""
Install the groundtruth kit into a repository (Windows, macOS, Linux).

    python install.py /path/to/your/repo            # project install (recommended)
    python install.py /path/to/your/repo --global   # also install the skill for all your repos
    python install.py /path/to/your/repo --copy     # copy skill folders instead of symlinking

Safe to re-run: it updates its own files and the marked block in AGENTS.md, and never
deletes your content.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
START, END = "<!-- groundtruth:start -->", "<!-- groundtruth:end -->"
CANONICAL = ".agents/skills"                 # read natively by Codex and other Agent Skills tools
MIRRORS = [".claude/skills", ".github/skills"]  # Claude Code, GitHub Copilot (VS Code / CLI / cloud agent)
GLOBAL_DIRS = ["~/.agents/skills", "~/.claude/skills", "~/.copilot/skills", "~/.codex/skills"]
INIT = '"""groundtruth tools. Tracing: from tools.groundtruth import trace, run, span, event"""\n' \
       "from .agent_trace import trace, run, span, event  # noqa: F401\n"


def say(msg):
    print("  " + msg)


def _remove(p: Path):
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.exists():
        shutil.rmtree(p)


def copy_tree(src: Path, dst: Path):
    _remove(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def link_or_copy(target: Path, link: Path, force_copy: bool) -> str:
    _remove(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    if not force_copy:
        try:
            os.symlink(os.path.relpath(target, link.parent), link, target_is_directory=True)
            return "symlink"
        except (OSError, NotImplementedError):
            pass  # Windows without developer mode, some filesystems
    shutil.copytree(target, link)
    return "copy"


def build_skill(dst: Path):
    """Skill folder + bundled scripts, so the skill also works on its own."""
    copy_tree(KIT / "skill" / "groundtruth", dst)
    (dst / "scripts").mkdir(exist_ok=True)
    for f in ("gt.py", "agent_trace.py", "viz.py"):
        shutil.copy2(KIT / "tools" / f, dst / "scripts" / f)


def merge_agents_md(repo: Path) -> str:
    tpl = (KIT / "templates" / "AGENTS.md").read_text(encoding="utf-8")
    block = tpl[tpl.index(START): tpl.index(END) + len(END)]
    p = repo / "AGENTS.md"
    if not p.exists():
        p.write_text(tpl, encoding="utf-8")
        return "created — fill in the 'Project facts' section"
    cur = p.read_text(encoding="utf-8")
    if START in cur and END in cur:
        p.write_text(cur[: cur.index(START)] + block + cur[cur.index(END) + len(END):], encoding="utf-8")
        return "updated the groundtruth block (your content untouched)"
    p.write_text(cur.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
    return "appended the groundtruth block (your content untouched)"


def ensure_claude_md(repo: Path) -> str:
    p = repo / "CLAUDE.md"
    if not p.exists():
        shutil.copy2(KIT / "templates" / "CLAUDE.md", p)
        return "created (imports AGENTS.md)"
    cur = p.read_text(encoding="utf-8")
    if "@AGENTS.md" in cur:
        return "already imports AGENTS.md"
    p.write_text("@AGENTS.md\n\n" + cur, encoding="utf-8")
    return "added '@AGENTS.md' import at the top"


def ensure_gitignore(repo: Path) -> str:
    p = repo / ".gitignore"
    cur = p.read_text(encoding="utf-8") if p.exists() else ""
    if ".groundtruth/" in cur:
        return "already ignores .groundtruth/"
    p.write_text((cur.rstrip() + "\n\n" if cur.strip() else "") + "# groundtruth: traces, scratch answers, index\n.groundtruth/\n",
                 encoding="utf-8")
    return "added .groundtruth/ (traces stay local)"


def main():
    ap = argparse.ArgumentParser(description="Install groundtruth into a repo.")
    ap.add_argument("repo", nargs="?", default=".", help="path to the repository (default: current folder)")
    ap.add_argument("--copy", action="store_true", help="copy skill mirrors instead of symlinking")
    ap.add_argument("--global", dest="glob", action="store_true", help="also install the skill in your user folders")
    ap.add_argument("--no-map", action="store_true", help="skip generating docs/CODEMAP.md")
    args = ap.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        sys.exit(f"Not a folder: {repo}")
    print(f"\nInstalling groundtruth into {repo}\n")

    tools = repo / "tools" / "groundtruth"
    tools.mkdir(parents=True, exist_ok=True)
    for f in ("gt.py", "agent_trace.py", "viz.py"):
        shutil.copy2(KIT / "tools" / f, tools / f)
    (tools / "__init__.py").write_text(INIT, encoding="utf-8")
    say("tools/groundtruth/           gt.py (map, flow, callers, verify, viz, trace) + agent_trace.py + viz.py")

    canonical = repo / CANONICAL / "groundtruth"
    build_skill(canonical)
    say(f"{CANONICAL}/groundtruth/  skill (Codex & other Agent Skills tools)")
    for m in MIRRORS:
        how = link_or_copy(canonical, repo / m / "groundtruth", args.copy)
        say(f"{m}/groundtruth/  {how}")

    say(f"AGENTS.md                    {merge_agents_md(repo)}")
    say(f"CLAUDE.md                    {ensure_claude_md(repo)}")

    flows = repo / "docs" / "flows"
    flows.mkdir(parents=True, exist_ok=True)
    tpl = flows / "_TEMPLATE.md"
    if not tpl.exists():
        shutil.copy2(KIT / "skill" / "groundtruth" / "references" / "flow-template.md", tpl)
    say("docs/flows/_TEMPLATE.md      template for verified flow docs")
    say(f".gitignore                   {ensure_gitignore(repo)}")

    if args.glob:
        for g in GLOBAL_DIRS:
            dst = Path(os.path.expanduser(g)) / "groundtruth"
            try:
                build_skill(dst)
                say(f"{g}/groundtruth  (global)")
            except OSError as e:
                say(f"{g}: skipped ({e})")

    if not args.no_map:
        print()
        r = subprocess.run([sys.executable, str(tools / "gt.py"), "--root", str(repo), "map"])
        if r.returncode != 0:
            say("CODEMAP generation failed — run: python tools/groundtruth/gt.py map")

    print("""
Done. Next:
  1. Open AGENTS.md and fill in 'Project facts' (5 lines — biggest single win against hallucination).
  2. Commit: AGENTS.md CLAUDE.md docs/ tools/groundtruth .agents .claude .github/skills
  3. Ask your agent (Claude Code, Codex, Copilot, Cursor...):
       "Use the groundtruth skill: explain the flow from <entry point> and write docs/flows/<name>.md"
  4. For LLM/agent code: add @trace(kind="llm"|"tool"|"node") and run
       python tools/groundtruth/gt.py trace view latest
  5. See everything visually (overview, flow explorer, agent run timelines):
       python tools/groundtruth/gt.py viz --open
""")


if __name__ == "__main__":
    main()
