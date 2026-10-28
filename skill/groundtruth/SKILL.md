---
name: groundtruth
description: Evidence-first protocol for understanding, tracing, debugging and reviewing code in this repo, especially AI-generated code and agentic/LLM flows. Use whenever someone asks how something works, where a flow goes, why something fails, or to review or fix AI-written code. Prevents hallucinated answers by requiring file:line citations, runtime checks and an automatic verification pass.
---

# groundtruth — answer from evidence, never from memory

Coding agents (you included) do not hold this repo in context. You see slices returned by
search and file reads. When a needed fact is missing, a model fills the gap with what code
*usually* looks like — that is where hallucinated functions, wrong line numbers and invented
flows come from. This skill closes the gap: **find → read → run → cite → verify.**

Tool: `python tools/groundtruth/gt.py <command>` from the repo root (pure Python 3.8+, no
dependencies). If the repo doesn't have it, the same script ships in this skill's `scripts/`
folder: `python <skill-dir>/scripts/gt.py --root . <command>`. If Python isn't available,
use `rg`/`grep` and follow the same rules.

## Pick the mode

| Request looks like | Mode |
|---|---|
| "How does X work?", "Where does this request go?", onboarding | **A. Explain a flow** |
| Error, wrong output, test failing, "why does…" | **B. Debug** |
| LLM/agent gives wrong/odd answers, tool loops, flaky runs | **C. Debug an agentic flow** → also read `references/agentic-debugging.md` |
| "Review this", "is this AI code safe to merge?", cleanup | **D. Review AI-written code** |

---

## A. Explain a flow

1. **Find the entry point.** Check `docs/flows/` for an existing doc, then `docs/CODEMAP.md`
   ("Entry points", "Agentic hotspots"). Otherwise `rg -n "<route|command|keyword>"`.
2. **Get the skeleton:** `gt.py flow <entry> --depth 4`. This is static and name-based —
   treat it as a map of *candidates*, not truth. Note every `ambiguous` and `dynamic` marker.
3. **Read each hop** you will mention. Open the file at the line; confirm what it does.
4. **Resolve the unknowns at runtime** (dynamic dispatch, registries, config-driven routing,
   which of two duplicate functions is really used): run a test, add a temporary log,
   use a breakpoint, or trace it (`references/agentic-debugging.md`). Mark these `[RAN]`.
5. **Write it down** using `references/flow-template.md` → `docs/flows/<flow-name>.md`
   (if the user wants a doc), or answer in the format below. For the diagram, paste the output of
   `gt.py flow <entry> --mermaid` (never draw one by hand), then mark which ⚡/⚠ boxes you confirmed at runtime.
6. **Verify** (mandatory, see "Verification pass").

## B. Debug

1. **Reproduce.** Get one command that shows the failure (test, script, curl). Save the exact
   error text. If you cannot reproduce, stop and ask for inputs/logs — do not fix blind.
2. **Locate.** Read the stack trace bottom-up; open each frame in *this repo*. If there is no
   trace, `gt.py flow` the entry point and bisect: add probes (log/assert/breakpoint) halfway
   along the flow, check which half is wrong, repeat.
3. **Hypothesise — at most 3**, ranked, each with the probe that would confirm or kill it.
   Run the probes one at a time. Kill hypotheses with evidence, not argument.
4. **Find the root cause**, not the symptom: the *first* place where data or state becomes
   wrong. Cite it `file:line` `[RAN]`.
5. **Check blast radius:** `gt.py callers <function>` before changing behaviour or signature.
   AI code often has near-duplicate functions — check CODEMAP "Possible duplicates" so you
   fix the one that actually runs.
6. **Fix minimally + lock it in:** write a failing test first (or a repro script), apply the
   smallest fix, rerun the repro and nearby tests. Remove temporary probes.
7. Report with the template below and run the verification pass.

## C. Debug an agentic / LLM flow

Read `references/agentic-debugging.md`. Short version:
instrument with `@trace` → run the failing input → `gt.py trace view latest` → find the
**first span whose output is wrong** (not the last one that crashed) → classify the failure
(context / prompt / tool / parsing / routing-state / model variance) → if flaky, run it again and
`gt.py trace diff <good> <bad>` to see where runs split → fix that layer → rerun.
To show the human what happened, include `gt.py trace view <run> --mermaid` (sequence diagram) and
point them to `gt.py viz` → Agent runs tab (timeline, first error, compare two runs).

## D. Review AI-written code

Run `gt.py map` and check the CODEMAP sections, then look for these AI-code failure patterns:

- **Invented APIs:** imports or attributes that don't exist in the installed version. Verify
  with `python -c "import pkg, inspect; print(pkg.__version__); print(inspect.signature(pkg.fn))"`.
- **Duplicates / dead code:** same function name in several files, identical bodies under
  different names, functions with zero callers (`gt.py callers <name>` → nothing).
- **Silent failure:** `except: pass`, broad excepts returning defaults, retries that hide errors.
- **Plausible-but-wrong logic:** off-by-one, wrong default, inverted condition, unit mismatch.
  Prove with a small test, not by reading.
- **Untraced LLM/tool calls:** every call to a model or tool should be wrapped with `@trace`.
- **Prompt/code drift:** prompt asks for a JSON shape the parser doesn't accept (or vice versa).
- **Unvalidated model output** used for control flow, SQL, shell, file paths.

List findings as `severity | file:line | problem | evidence | suggested fix`.

---

## Answer format (all modes)

```
**Answer:** 1–3 sentences.

**Evidence**
| Claim | Where | How known |
|---|---|---|
| Request enters at `handle_chat` | `app/api.py:41` | [READ] |
| Router picks `search` node for this input | `app/graph.py:88` | [RAN] trace 20261028-… |

**Not verified / unknown:** anything you could not confirm, and the check that would settle it.
**Next step:** one concrete command or check.
```

## Verification pass (mandatory before you reply)

1. Save your draft answer to `.groundtruth/answer.md`.
2. Run `python tools/groundtruth/gt.py verify .groundtruth/answer.md`.
3. Fix every ❌ (missing file, bad line, symbol not in repo). Re-check every ⚠.
4. Only then send the answer. If something still can't be verified, move it to
   "Not verified / unknown" — do not delete the doubt, surface it.

## Visuals for humans

- `gt.py flow <func> --mermaid` — call diagram; `gt.py trace view <run> --mermaid` — sequence diagram.
  Both render in GitHub, GitLab, VS Code (Markdown preview), Notion and most docs tools.
- `gt.py viz [--open]` — one offline HTML file (`.groundtruth/report.html`): overview of entry points,
  AI hotspots, runtime-only spots and duplicates; a searchable flow explorer (calls / called by);
  agent run timelines with the first error and run-to-run comparison. Suggest it when someone is new to the
  repo, reviewing an AI-written change, or debugging an agent. Regenerate after code changes or new runs.

## Hard stops

- After ~5 searches with no hit, report "not found" with the patterns you tried.
- Never paste a function body you have not read in this session.
- Never claim a test passes without running it.
- If two definitions could be the one that runs, say so and prove which with a runtime check.
