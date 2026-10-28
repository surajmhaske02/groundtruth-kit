"""
End-to-end tests: install the kit into a copy of examples/demo-agent and check every command
against the problems planted in that repo. Standard library only:

    python -m unittest discover -s tests -v
"""
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo-agent"


def run(args, cwd, env=None, check=False):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    e.update(env or {})
    p = subprocess.run([sys.executable] + args, cwd=str(cwd), env=e, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if check and p.returncode != 0:
        raise AssertionError(f"{args} failed ({p.returncode}):\n{p.stdout}\n{p.stderr}")
    return p


class DemoRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="gt-test-"))
        cls.repo = cls.tmp / "demo"
        shutil.copytree(DEMO, cls.repo)
        (cls.repo / ".git").mkdir()  # repo-root marker; git itself is not needed
        cls.install = run([str(ROOT / "install.py"), str(cls.repo)], ROOT, check=True)
        cls.gt = str(cls.repo / "tools" / "groundtruth" / "gt.py")
        # three agent runs: ok (search_docs), error (calculator path), error (KeyError in tool)
        run(["-m", "app.api", "refund"], cls.repo, {"SEED": "1"})
        run(["-m", "app.api", "refund"], cls.repo, {"SEED": "0"})
        run(["-m", "app.api", "what is the refund policy"], cls.repo, {"SEED": "1"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def gtrun(self, *args, check=True):
        return run([self.gt] + list(args), self.repo, check=check)

    # ------------------------------------------------------------------ install
    def test_install_creates_everything(self):
        for p in ["AGENTS.md", "CLAUDE.md", "docs/CODEMAP.md", "docs/flows/_TEMPLATE.md",
                  "tools/groundtruth/gt.py", "tools/groundtruth/agent_trace.py", "tools/groundtruth/viz.py",
                  ".agents/skills/groundtruth/SKILL.md", ".agents/skills/groundtruth/scripts/viz.py",
                  ".claude/skills/groundtruth/SKILL.md", ".github/skills/groundtruth/SKILL.md"]:
            self.assertTrue((self.repo / p).exists(), p)
        self.assertIn("@AGENTS.md", (self.repo / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertIn(".groundtruth/", (self.repo / ".gitignore").read_text(encoding="utf-8"))

    def test_install_is_idempotent_and_keeps_user_content(self):
        tmp = Path(tempfile.mkdtemp(prefix="gt-idem-"))
        try:
            (tmp / ".git").mkdir()
            (tmp / "AGENTS.md").write_text("# Team rules\nUse black.\n", encoding="utf-8")
            (tmp / "CLAUDE.md").write_text("Be brief.\n", encoding="utf-8")
            for _ in range(2):
                run([str(ROOT / "install.py"), str(tmp), "--copy", "--no-map"], ROOT, check=True)
            agents = (tmp / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(agents.startswith("# Team rules"))
            self.assertEqual(agents.count("<!-- groundtruth:start -->"), 1)
            claude = (tmp / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertEqual(claude.count("@AGENTS.md"), 1)
            self.assertIn("Be brief.", claude)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ map
    def test_codemap_finds_planted_problems(self):
        cm = (self.repo / "docs" / "CODEMAP.md").read_text(encoding="utf-8")
        self.assertIn("app/api.py:18", cm)                     # HTTP entry point
        self.assertIn("chat.completions.create", cm)           # LLM call
        self.assertIn('tool = TOOLS[d["tool"]]', cm)           # registry dispatch
        self.assertIn("`parse_output`: `app/utils.py:1`, `legacy/utils.py:1`", cm)
        self.assertIn("`format_answer` (`app/utils.py:7`) ≈ `format_answer_v2` (`legacy/utils.py:5`)", cm)

    # ------------------------------------------------------------------ flow / callers
    def test_flow_resolves_chain_and_flags_runtime_dispatch(self):
        out = self.gtrun("flow", "SupportAgent.run", "--depth", "2").stdout
        self.assertIn("SupportAgent.plan  app/agent.py:28", out)
        self.assertIn("LLMClient.complete  app/llm.py:33", out)   # self.llm = LLMClient() inferred
        self.assertIn("⚡ DYNAMIC tool(...)", out)
        self.assertNotRegex(out, r":\d+ ~probable")              # every hop resolved exactly, no name guesses

    def test_flow_ambiguous_name_asks_for_a_file(self):
        p = self.gtrun("flow", "parse_output", check=False)
        self.assertEqual(p.returncode, 2)
        self.assertIn("legacy/utils.py", p.stdout)

    def test_flow_handles_inheritance_and_same_named_classes(self):
        tmp = Path(tempfile.mkdtemp(prefix="gt-inh-"))
        try:
            (tmp / ".git").mkdir()
            (tmp / "a.py").write_text(textwrap.dedent("""
                class Base:
                    def __init__(self):
                        self.client = Client()
                    def helper(self):
                        return self.client.send_msg()

                class Child(Base):
                    def run(self):
                        self.helper()

                class Client:
                    def send_msg(self):
                        return 1

                def main():
                    c = Child()
                    c.run()
            """), encoding="utf-8")
            (tmp / "b.py").write_text("class Child:\n    def __init__(self):\n        pass\n    def run(self):\n        pass\n",
                                      encoding="utf-8")
            out = run([self.gt, "--root", str(tmp), "flow", "a.py:main", "--depth", "4"], tmp, check=True).stdout
            self.assertIn("Child.run  a.py:9", out)
            self.assertIn("Base.helper  a.py:5", out)
            self.assertIn("Client.send_msg  a.py:13", out)
            self.assertNotIn("b.py", out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_callers_include_registry_string_and_config(self):
        out = self.gtrun("callers", "search_docs").stdout
        self.assertRegex(out, r"app/tools\.py:\d+\s+\[ref")
        self.assertIn("[string]", out)
        self.assertIn("[config]", out)
        self.assertIn("in test_search", out)

    def test_callers_reports_dead_code(self):
        self.assertIn("Possibly dead code", self.gtrun("callers", "format_answer_v2").stdout)

    # ------------------------------------------------------------------ verify
    def test_verify_catches_hallucinations(self):
        p = self.gtrun("verify", "answer_example.md", check=False)
        self.assertEqual(p.returncode, 1)
        out = p.stdout
        for bad in ("app/auth.py:12", "`validate_session`", "`requests.post`", "`SupportAgent.retry_with_backoff`"):
            self.assertRegex(out, "❌ " + re.escape(bad))
        self.assertIn("`route` is defined at app/agent.py:51", out)
        self.assertIn("`Graph` exists but has no `run`", out)
        self.assertIn("only 2/3 lines match", out)

    def test_verify_passes_a_correct_answer_and_checks_diagrams(self):
        good = self.repo / "good.md"
        good.write_text("Entry is `handle_chat` (app/api.py:18), which calls `run_agent` (app/agent.py:55).\n\n"
                        "```mermaid\nflowchart TD\n  a[\"x<br/>app/agent.py:55\"] --> b[\"y<br/>app/nothere.py:3\"]\n```\n",
                        encoding="utf-8")
        p = self.gtrun("verify", "good.md", check=False)
        self.assertEqual(p.returncode, 1)              # the invented diagram label is caught
        self.assertIn("❌ app/nothere.py:3", p.stdout)
        good.write_text("Entry is `handle_chat` (app/api.py:18), which calls `run_agent` (app/agent.py:55).\n", encoding="utf-8")
        self.assertEqual(self.gtrun("verify", "good.md", check=False).returncode, 0)

    # ------------------------------------------------------------------ traces
    def test_trace_view_finds_first_error(self):
        out = self.gtrun("trace", "view", "latest").stdout
        self.assertIn("FIRST ERROR  [tool] search_docs", out)
        self.assertIn("KeyError", out)

    def test_trace_diff_pins_nondeterminism_to_llm_step(self):
        out = self.gtrun("trace", "diff", "latest~2", "latest~1").stdout
        self.assertIn("FIRST DIFFERENT RESULT (innermost): [llm] LLMClient.complete", out)
        self.assertIn("SAME input, DIFFERENT result", out)
        self.assertIn("FIRST DIFFERENT PATH", out)

    def test_trace_diff_treats_different_errors_as_different(self):
        out = self.gtrun("trace", "diff", "latest~1", "latest").stdout
        self.assertRegex(out, r"≠ \[api\] handle_chat")      # TypeError vs KeyError are not "the same"

    # ------------------------------------------------------------------ visuals
    def test_mermaid_exports(self):
        flow = self.gtrun("flow", "handle_chat", "--mermaid").stdout
        self.assertIn("flowchart TD", flow)
        self.assertIn("class n0 entry", flow)
        self.assertRegex(flow, r"class [n0-9,]+ llm")
        seq = self.gtrun("trace", "view", "latest", "--mermaid").stdout
        self.assertIn("sequenceDiagram", seq)
        self.assertIn("--x-", seq)                     # error return arrow

    def test_viz_report(self):
        out = self.repo / "report.html"
        self.gtrun("viz", "--out", str(out))
        html = out.read_text(encoding="utf-8")
        data = json.loads(re.search(r'<script type="application/json" id="gt-data">(.*?)</script>', html, re.S).group(1))
        self.assertGreater(len(data["nodes"]), 15)
        self.assertEqual(len(data["runs"]), 3)
        self.assertEqual(data["stats"]["run_errors"], 2)
        self.assertNotIn("http://", html.split("<script")[0])  # no external resources in the page shell
        self.assertNotIn("src=\"http", html)


class Repo(unittest.TestCase):
    def test_skill_scripts_match_tools(self):
        for f in ("gt.py", "agent_trace.py", "viz.py"):
            self.assertTrue(filecmp.cmp(ROOT / "tools" / f, ROOT / "skill" / "groundtruth" / "scripts" / f, shallow=False),
                            f"skill/groundtruth/scripts/{f} is stale — run: python scripts/sync_skill.py")

    def test_skill_frontmatter(self):
        text = (ROOT / "skill" / "groundtruth" / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"---\nname: (\S+)\ndescription: (.+?)\n---\n", text, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "groundtruth")
        self.assertLess(len(m.group(2)), 1024)


if __name__ == "__main__":
    unittest.main()
