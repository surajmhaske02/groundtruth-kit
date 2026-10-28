# Contributing

Thanks for helping. The project has two rules that keep it useful:

1. **No dependencies.** Everything runs on the Python standard library (3.8+), and the HTML report works offline.
2. **Never guess silently.** When static analysis can't be sure, mark it (⚡ runtime-only, ⚠ ambiguous, ~ probable) instead of picking an answer.

## Layout

```
tools/            gt.py, agent_trace.py, viz.py — the source of truth
skill/groundtruth SKILL.md + references; scripts/ is a copy of tools/ (run scripts/sync_skill.py)
templates/        AGENTS.md and CLAUDE.md that install.py adds to a repo
examples/         demo-agent — a deliberately messy repo used by the tests
tests/            unittest suite (python -m unittest discover -s tests -v)
```

## Workflow

```bash
python scripts/sync_skill.py          # after editing anything in tools/
python -m unittest discover -s tests -v
```

If you find a case where `flow` resolves a call to the wrong function, add a small reproduction to
`tests/` — wrong answers are worse than missing ones.
