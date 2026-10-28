"""HTTP layer (framework-free stand-in for FastAPI)."""
from app.agent import run_agent
from tools.groundtruth import trace


class App:
    def post(self, path):
        def deco(fn):
            return fn
        return deco


app = App()


@app.post("/chat")
@trace(kind="api")
def handle_chat(payload):
    question = payload["question"]
    return {"answer": run_agent(question)}


if __name__ == "__main__":
    import sys
    print(handle_chat({"question": sys.argv[1] if len(sys.argv) > 1 else "what is the refund policy"}))
