# Changelog

## 0.1.0 — 2026-10-28

First public release.

- `AGENTS.md` grounding rules and a `CLAUDE.md` import, so Claude Code, Codex, Copilot, Cursor and others follow the same rules.
- `groundtruth` skill (Agent Skills format) with four playbooks: explain a flow, debug, debug an agent, review AI-written code.
- `gt.py map` — CODEMAP with entry points, AI hotspots, runtime-only dispatch, duplicate functions and renamed clones.
- `gt.py flow` / `callers` — static call tree (Python scoping, imports, type hints, base classes, callbacks) and every reference including strings and config.
- `gt.py verify` — checks that citations, symbols, quoted code and diagram labels in an AI answer exist.
- `agent_trace.py` + `gt.py trace` — zero-dependency tracing for LLM / tool / node steps; view, show, diff two runs.
- `gt.py viz` — offline HTML report: overview, flow explorer, agent-run timelines with run comparison.
- Mermaid export for flows (`flow --mermaid`) and agent runs (`trace view --mermaid`).
- Python 3.8+ only, no dependencies. Tested on Linux, macOS and Windows.
