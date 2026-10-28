# AGENTS.md

Instructions for every AI coding agent working in this repo
(Codex, Copilot, Cursor, Gemini CLI, Windsurf, Aider, Claude Code via CLAUDE.md, ...).

## Project facts (fill this in — agents read it every session)

- What this system does (1–2 lines):
- Main entry points (file:function):
- How to run it locally:
- How to run tests:
- Agentic/LLM parts (where prompts, tools, graphs live):
- Known traps (things that look wrong but are intentional):

<!-- groundtruth:start -->
## Grounding rules (non-negotiable)

This codebase was largely written by AI models. Nobody holds it all in their head,
so every answer about it must come from evidence, not from what code "usually" looks like.

1. **No claim without a citation.** Every statement about this code cites `path/to/file.ext:LINE`
   that you actually opened in this session. If you did not read it, you do not know it.
2. **Label your evidence.** Tag claims as `[READ]` (saw the code), `[RAN]` (observed at runtime:
   test, log, trace, REPL), or `[INFERRED]` (reasoning). Never present `[INFERRED]` as fact.
3. **"Not found" is a valid answer.** If a search turns up nothing, say what you searched
   (`rg` pattern, paths) and stop. Never invent a function, file, flag, config key or API.
4. **Check that external APIs exist before using them.** Read the installed library source
   or run `python -c "import pkg; print(pkg.__version__); help(pkg.thing)"`. Do not trust memory.
5. **Reproduce before you fix.** A bug fix starts with a command that shows the failure and ends
   with the same command passing. No repro → you are guessing.
6. **Runtime beats reading** for anything dynamic: LLM outputs, routing, registries, DI,
   `getattr`, config-driven behaviour. Trace it (see below), don't reason about it.

## Map of the code (start here, not with random grep)

- `docs/CODEMAP.md` — generated index: entry points, LLM/tool hotspots, dynamic dispatch, duplicates.
  Regenerate: `python tools/groundtruth/gt.py map`
- `docs/flows/*.md` — verified walkthroughs of important flows. Read the relevant one first;
  update it when you change that flow.

## Tools (use them — they are faster and more reliable than guessing)

```bash
python tools/groundtruth/gt.py map                      # rebuild docs/CODEMAP.md
python tools/groundtruth/gt.py flow <func|Class.method|file.py:func>   # static call tree
python tools/groundtruth/gt.py callers <name>           # who calls / registers it (blast radius)
python tools/groundtruth/gt.py verify <answer.md>       # check every citation & symbol is real
python tools/groundtruth/gt.py trace view latest        # last agent run as a step tree
python tools/groundtruth/gt.py trace diff <runA> <runB> # first step where two runs diverge
python tools/groundtruth/gt.py flow <func> --mermaid    # call diagram for docs/PRs (renders on GitHub)
python tools/groundtruth/gt.py trace view latest --mermaid  # sequence diagram of an agent run
python tools/groundtruth/gt.py viz                      # HTML report for humans: .groundtruth/report.html
```

When you explain a flow or a bug to a human, include the Mermaid diagram from these commands
instead of drawing one yourself — a hand-drawn diagram can be as hallucinated as prose.

For explaining, debugging, or reviewing code here, use the **groundtruth** skill.

## Rules for changing AI-written code

- Smallest diff that fixes the root cause. No drive-by refactors.
- Before writing a helper, check `docs/CODEMAP.md` → "Possible duplicates" and search for an existing one.
- No bare `except:` / `except Exception: pass`. Errors must surface or be logged with context.
- Every LLM call, tool call and graph node keeps (or gets) a `@trace(...)` decorator.
- Run `gt.py callers <changed function>` before changing a signature; update every caller.
- If you change a flow, update its `docs/flows/<name>.md`.
- Finish with: what changed, why (root cause with file:line), how it was verified (`[RAN]` command).
<!-- groundtruth:end -->
