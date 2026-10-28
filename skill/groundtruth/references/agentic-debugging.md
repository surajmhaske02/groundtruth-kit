# Debugging agentic / LLM flows

Agentic code is hard to debug by reading because the important decisions (which tool,
which branch, what text) are made **at runtime by a model**. So: record every step, then
read the recording.

## 1. Instrument (once)

`tools/groundtruth/agent_trace.py` — zero dependencies, writes JSONL to `.groundtruth/traces/`.

```python
from tools.groundtruth import trace, run, span, event
# If that import fails (repo root not on sys.path), copy agent_trace.py into your own
# package — it is one file with no dependencies — and `from mypkg.agent_trace import trace, ...`

@trace(kind="llm")              # every model call
def call_model(messages, **kw): ...

@trace(kind="tool")             # every tool the agent can use
def search_docs(query: str): ...

@trace(kind="node")             # every graph node / agent step / chain stage
def plan(state): ...

with run("user question", input=question):   # one run per request (optional:
    answer = agent(question)                  # a run starts automatically otherwise)

event("route", next="search", reason=state["why"])   # record decisions
with span("retrieve", kind="retrieval") as s:         # trace a block, not a function
    docs = retriever.get(q); s.set(output=[d.id for d in docs])
```

Works with sync and async functions, any framework (LangGraph nodes, CrewAI tools, plain
OpenAI/Anthropic SDK calls). Secrets in argument names like `api_key`, `token`, `password`
are masked. Disable with `GT_TRACE=0`. For production, use OpenTelemetry-based tracing
(Langfuse, Arize Phoenix, LangSmith, etc.) — same mental model, this is the local version.

## 2. Look

```bash
python tools/groundtruth/gt.py trace list                 # recent runs, status, errors
python tools/groundtruth/gt.py trace view latest          # tree of steps with in/out previews
python tools/groundtruth/gt.py trace view <run> --full    # untruncated
python tools/groundtruth/gt.py trace show <run> <span>    # one step, full JSON
python tools/groundtruth/gt.py trace diff <good> <bad>    # first structural + first output divergence
python tools/groundtruth/gt.py trace view latest --mermaid # sequence diagram (paste into a PR or issue)
python tools/groundtruth/gt.py viz --open                  # visual timeline of every run + compare two runs
```

In the report's **Agent runs** tab each step is a bar placed when it started and as long as it took
(LLM pink, tool green, node purple, error red, unfinished striped). Tap a step for its input, output and
error. "Compare with another run" lines both runs up step by step and names the first step whose result
differs, and whether its input was the same (model variance) or not (cause is upstream).

## 3. Find the first bad step

The crash is usually *downstream* of the real bug. Walk the tree top-down and stop at the
**first span whose output is wrong given its input**. That span's layer is where the fix goes.
Spans marked `did not finish` mean a crash/hang/timeout inside them.

## 4. Classify the failure

| Symptom in the trace | Layer | Typical fix |
|---|---|---|
| Model input is missing the needed fact | **Context / retrieval** | Fix retrieval query, chunking, filters; log retrieved ids |
| Input has the fact, output ignores it or invents | **Prompt / model** | Tighter instruction, examples, ask for citations, lower temperature, smaller task per call |
| Output fine, but parse step fails or loses fields | **Parsing / schema** | Structured output / JSON schema, validate with pydantic, show the raw text in the error |
| Tool span errors or returns empty | **Tool** | Fix the tool; return explicit errors to the model instead of `None` |
| Wrong node/tool chosen | **Routing / state** | Log the state the router saw (`event`), check the condition, check state keys mutated earlier |
| Same tool called again and again | **Loop control** | Max-step limit, feed tool errors back clearly, dedupe calls |
| Works sometimes | **Variance** | Run twice, `trace diff`, then pin temperature/seed, cache tool results to replay |

## 5. Make failures reproducible

- Save the failing input as a test fixture.
- Pin `temperature=0` (and `seed` if the API supports it) while debugging.
- Record tool outputs from a bad run and replay them so you debug the agent logic,
  not the network.
- Keep a small "golden set" of inputs → expected properties (not exact text) and run it
  after every prompt or code change.

## 6. Questions developers ask, and how to answer them with evidence

| Question | Evidence to collect |
|---|---|
| "Why did the agent call tool X?" | `trace view` → the `llm` span right before the tool span: its output contains the tool call; the input shows what it saw |
| "Where does this prompt come from?" | `rg -n "<distinctive phrase from prompt>"` → file:line; check for templating/overrides |
| "Which model/params are used?" | Trace the `llm` span inputs; config files; env vars — `[RAN]` beats reading config |
| "Why is it slow?" | `trace view` durations; sort the longest spans |
| "Why different answer today?" | `trace diff` yesterday's run vs today's |
