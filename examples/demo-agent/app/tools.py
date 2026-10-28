"""Tools the agent can call."""
from tools.groundtruth import trace

DOCS = [{"id": 1, "text": "Refunds within 30 days"}, {"title": "no id here", "text": "Shipping is free"}]


@trace(kind="tool")
def search_docs(query):
    hits = [d for d in DOCS if any(w in d["text"].lower() for w in query.lower().split())]
    return [{"doc_id": d["id"], "text": d["text"]} for d in hits]


@trace(kind="tool")
def calculator(expr):
    return eval(expr)


TOOLS = {"search_docs": search_docs, "calculator": calculator}
