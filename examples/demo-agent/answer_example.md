**Answer:** A chat request enters at `handle_chat` (app/api.py:18), which calls `run_agent` in app/agent.py:55.
`SupportAgent.plan` (app/agent.py:28) asks the model through `LLMClient.complete`.
Then `validate_session` checks the user token (app/auth.py:12).
The router `route` is defined at app/agent.py:30.
Tool results are formatted by `format_answer` in `utils.py`.
Retries are handled by `SupportAgent.retry_with_backoff`, and `Graph.run` executes the nodes.
It uses `requests.post` to call the vector DB, and `json.loads` to parse the reply.

Existing code (app/tools.py:8-10):
```python
def search_docs(query):
    hits = [d for d in DOCS if any(w in d["text"].lower() for w in query.lower().split())]
    return [{"doc_id": d["id"], "text": d["text"]} for d in hits]
```

As currently written in app/tools.py lines 8-10:
```python
def search_docs(query):
    hits = [d for d in DOCS if query in d["text"]]
    return [{"doc_id": d["id"], "text": d["text"]} for d in hits]
```
