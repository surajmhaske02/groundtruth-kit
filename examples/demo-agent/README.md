# demo-agent — a deliberately messy AI-style agent

Planted problems: a duplicate `parse_output` (app/ vs legacy/), a renamed copy-paste clone
(`format_answer_v2`), tool dispatch through a registry (`TOOLS[...]`), a data bug that crashes a
tool (`KeyError: 'id'`), and a nondeterministic "LLM" (seeded by `SEED`). `answer_example.md` is
an AI answer with invented files, functions and a wrong line number.

```bash
cd examples/demo-agent && git init -q
python ../../install.py .
python tools/groundtruth/gt.py flow handle_chat
python tools/groundtruth/gt.py callers search_docs
python tools/groundtruth/gt.py verify answer_example.md
SEED=1 python -m app.api refund ; SEED=0 python -m app.api refund
python tools/groundtruth/gt.py trace view latest
python tools/groundtruth/gt.py trace diff latest~1 latest
SEED=1 python -m app.api "what is the refund policy" ; python tools/groundtruth/gt.py trace view latest
python tools/groundtruth/gt.py flow handle_chat --mermaid     # diagram for docs / PRs
python tools/groundtruth/gt.py trace view latest --mermaid    # sequence diagram of the crash
python tools/groundtruth/gt.py viz --open                     # the visual report
```
(On Windows PowerShell use `$env:SEED=1; python -m app.api refund`.)
