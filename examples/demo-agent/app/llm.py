"""Fake OpenAI-style client so the demo runs offline."""
import os
import random

from tools.groundtruth import trace


class _Completions:
    def create(self, model, messages, temperature=0.7):
        rng = random.Random(int(os.environ.get("SEED", "0")))
        q = messages[-1]["content"]
        if "refund" in q and rng.random() < 0.5:
            return {"tool": "search_docs", "args": {"query": q}}
        if "refund" in q:
            return {"tool": "calculator", "args": {"expr": "2+2"}}
        return {"answer": "I don't know"}


class _Chat:
    completions = _Completions()


class FakeOpenAI:
    chat = _Chat()


class LLMClient:
    def __init__(self, model="gpt-x"):
        self.client = FakeOpenAI()
        self.model = model

    @trace(kind="llm")
    def complete(self, messages):
        return self.client.chat.completions.create(model=self.model, messages=messages)
