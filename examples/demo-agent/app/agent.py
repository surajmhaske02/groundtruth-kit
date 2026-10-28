"""Tiny agent loop: LLM picks a tool, tool runs, answer is formatted."""
from app.llm import LLMClient
from app.tools import TOOLS, search_docs
from app.utils import parse_output, format_answer
from tools.groundtruth import trace, event


class Graph:
    def __init__(self):
        self.nodes, self.edges = {}, {}

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_conditional_edges(self, src, router):
        self.edges[src] = router


class SupportAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.graph = Graph()
        self.graph.add_node("plan", self.plan)
        self.graph.add_node("act", self.act)
        self.graph.add_conditional_edges("plan", route)

    @trace(kind="node")
    def plan(self, state):
        decision = self.llm.complete([{"role": "user", "content": state["question"]}])
        state["decision"] = decision
        return state

    @trace(kind="node")
    def act(self, state):
        d = state["decision"]
        tool = TOOLS[d["tool"]]
        state["results"] = tool(**d["args"])
        return state

    def run(self, question):
        state = {"question": question}
        state = self.plan(state)
        nxt = route(state)
        event("route", next=nxt, decision=state["decision"])
        if nxt == "act":
            state = self.act(state)
            return trace(kind="step")(format_answer)(state["results"], question)
        return parse_output(state["decision"])


def route(state):
    return "act" if "tool" in state["decision"] else "end"


def run_agent(question):
    agent = SupportAgent()
    return agent.run(question)
