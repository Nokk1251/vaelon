"""Several tasks at once, several tools at once, the lookup cache, cancel, spoken mode, legal notices (all offline)."""
import os
import sys
import tempfile
import threading
import time
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path  # noqa: E402

from vaelon import server, updates  # noqa: E402
from vaelon.agent import Agent, _calls  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM, _calls_json  # noqa: E402
from vaelon.memory import Memory  # noqa: E402
from vaelon.security.policy import Risk  # noqa: E402
from vaelon.tools import registry  # noqa: E402

COUNT = {"slow_a": 0, "slow_b": 0, "cached": 0, "danger": 0}


@registry.tool("t_slow_a", "test lookup A", {"q": "text"})
def _slow_a(ctx, q):
    COUNT["slow_a"] += 1
    time.sleep(0.4)
    return f"A:{q}"


@registry.tool("t_slow_b", "test lookup B", {"q": "text"})
def _slow_b(ctx, q):
    COUNT["slow_b"] += 1
    time.sleep(0.4)
    return f"B:{q}"


@registry.tool("t_cached", "test cached lookup", {"q": "text"}, untrusted=True)
def _cached(ctx, q):
    COUNT["cached"] += 1
    return f"C:{q}:{COUNT['cached']}"


@registry.tool("t_danger", "test dangerous action", {"q": "text"}, risk=Risk.DANGEROUS)
def _danger(ctx, q):
    COUNT["danger"] += 1
    return "done"


def agent(replies, **kw):
    a = Agent(Config(provider="mock"), llm=MockLLM(replies), memory=Memory(":memory:"), load_extensions=False, **kw)
    a.use_intents = False
    return a


class ParallelTools(unittest.TestCase):
    def test_model_calls_become_one_or_many(self):
        self.assertEqual(_calls_json([("now", "")]), '{"tool": "now", "args": {}}')
        many = _calls_json([("weather", '{"place": "Sofia"}'), ("weather", '{"place": "Varna"}')])
        self.assertIn('"tools"', many)
        import json

        self.assertEqual(_calls(json.loads(many)), [("weather", {"place": "Sofia"}), ("weather", {"place": "Varna"})])
        self.assertEqual(len(_calls({"tools": [{"tool": "now", "args": {}}] * 3})), 1)  # duplicates collapse

    def test_safe_tools_run_at_the_same_time(self):
        a = agent(['{"tools": [{"tool": "t_slow_a", "args": {"q": "1"}}, {"tool": "t_slow_b", "args": {"q": "2"}}]}',
                   '{"final": "both"}'])
        events = []
        t0 = time.time()
        self.assertEqual(a.run("compare one and two", on_event=lambda k, d: events.append((k, d))), "both")
        self.assertLess(time.time() - t0, 0.75)  # 0.4 s + 0.4 s in sequence would be 0.8 s
        seen = a.llm.seen[1][-1]["content"]
        self.assertIn("TOOL_RESULT t_slow_a:\nA:1", seen)
        self.assertIn("TOOL_RESULT t_slow_b:\nB:2", seen)
        self.assertEqual([d for k, d in events if k == "tool"], ["t_slow_a", "t_slow_b"])
        self.assertIn(("detail", "1"), events)

    def test_dangerous_tool_in_a_batch_still_needs_approval(self):
        before = COUNT["danger"]
        a = agent(['{"tools": [{"tool": "t_slow_a", "args": {"q": "1"}}, {"tool": "t_danger", "args": {"q": "x"}}]}',
                   '{"final": "ok"}'])
        a.run("do both")
        self.assertEqual(COUNT["danger"], before)  # deny_all approver: never executed
        self.assertIn("DENIED", a.llm.seen[1][-1]["content"])


class LookupCache(unittest.TestCase):
    def test_repeated_lookup_is_served_from_the_cache_and_stays_tainted(self):
        registry.CACHE_TTL["t_cached"] = 60
        try:
            a = agent([])
            first = registry.Ctx(a.cfg, extra={"cache": a.tool_cache})
            r1 = registry.execute(first, "t_cached", {"q": "x"})
            second = registry.Ctx(a.cfg, extra={"cache": a.tool_cache})
            r2 = registry.execute(second, "t_cached", {"q": "x"})
            self.assertEqual(r1, r2)
            self.assertTrue(second.tainted)  # cached outside content is still outside content
            self.assertNotEqual(registry.execute(second, "t_cached", {"q": "y"}), r1)
            other = agent([])  # another Vaelon instance has its own cache
            self.assertNotEqual(registry.execute(registry.Ctx(other.cfg, extra={"cache": other.tool_cache}),
                                                 "t_cached", {"q": "x"}), r1)
        finally:
            registry.CACHE_TTL.pop("t_cached", None)


class GateLLM:
    """Every chat() waits until `need` requests are inside at the same time - impossible unless jobs run in parallel."""

    def __init__(self, need=2):
        self.barrier = threading.Barrier(need, timeout=4)
        self.hold = threading.Event()

    def chat(self, messages):
        self.barrier.wait()
        return '{"final": "answer to %s"}' % messages[-1]["content"].split("\n")[0][-6:]


class SlowLLM:
    def __init__(self):
        self.calls = 0

    def chat_stream(self, messages, **kw):
        self.calls += 1
        for _ in range(100):
            time.sleep(0.03)
            yield "word "

    def chat(self, messages):
        return "never used"


def wait_done(svc, jid, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        if svc.jobs[jid].status == "done":
            return svc.jobs[jid]
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class ParallelTasks(unittest.TestCase):
    def service(self, llm):
        cfg = Config(provider="mock")

        def make(c, approver):
            a = Agent(c, llm=llm, approver=approver, memory=Memory(":memory:"), load_extensions=False)
            a.use_intents = False
            return a

        return server.Service(cfg, make)

    def test_two_tasks_think_at_the_same_time_and_share_one_history(self):
        svc = self.service(GateLLM(2))
        j1, j2 = svc.start("task number one111"), svc.start("task number two222")
        a, b = wait_done(svc, j1), wait_done(svc, j2)
        self.assertTrue(a.answer.startswith("answer to") and b.answer.startswith("answer to"), (a.answer, b.answer))
        self.assertNotEqual(a.answer, b.answer)
        self.assertEqual(len(svc.agent().history), 4)  # both exchanges landed in the one shared conversation
        self.assertEqual(a.steps[0]["label"], "started")
        self.assertEqual(a.steps[-1]["label"], "done")
        self.assertIn("text", a.snapshot())

    def test_fork_shares_memory_and_history_but_not_the_approver(self):
        a = agent([])
        twin = a.fork(lambda req: True)
        self.assertIs(twin.history, a.history)
        self.assertIs(twin.memory, a.memory)
        self.assertIsNot(twin.approver, a.approver)

    def test_cancel_stops_a_running_task_and_leaves_no_trace(self):
        llm = SlowLLM()
        svc = self.service(llm)
        jid = svc.start("write a very long story")
        end = time.time() + 3
        while not svc.jobs[jid].partial and time.time() < end:
            time.sleep(0.02)
        self.assertTrue(svc.cancel(jid))
        job = wait_done(svc, jid)
        self.assertTrue(job.cancelled)
        self.assertEqual(job.answer, "")
        self.assertEqual(svc.agent().history, [])
        self.assertFalse(svc.cancel(jid))  # already finished
        self.assertEqual(job.steps[-1]["label"], "cancelled")


class SpokenAndNotices(unittest.TestCase):
    def test_spoken_mode_asks_for_a_short_answer(self):
        a = agent(['{"final": "ok"}', '{"final": "ok"}'])
        a.run("tell me about the moon", spoken=True)
        a.run("tell me about the sun")
        self.assertIn("SPOKEN CONVERSATION", a.llm.seen[0][-1]["content"])
        self.assertNotIn("SPOKEN CONVERSATION", a.llm.seen[1][-1]["content"])

    def test_author_credit_is_shown(self):
        import vaelon
        from vaelon import catalog

        about = catalog.about()
        self.assertEqual(about["license"], "GPL-3.0-or-later")
        self.assertTrue(about["author"])
        self.assertIn(vaelon.__author__, about["text"])
        self.assertIn("created by", about["text"])
        self.assertTrue(about["author_url"].startswith("https://github.com/"))
        self.assertIn(vaelon.__author__, Path(os.path.dirname(__file__), "..", "NOTICE").read_text("utf-8"))
        self.assertIn(vaelon.__author__, Path(os.path.dirname(__file__), "..", "README.md").read_text("utf-8"))
        root = os.path.join(os.path.dirname(__file__), "..")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", Path(root, "LICENSE").read_text("utf-8")[:300])
        self.assertIn("7(b)", Path(root, "NOTICE").read_text("utf-8"))

    def test_update_check_compares_versions(self):  # the rest of the check: tests/test_updates.py
        self.assertTrue(updates.newer("1.2.0", "1.1.9"))
        self.assertFalse(updates.newer("0.2.0", "0.2.0"))
        self.assertFalse(updates.newer("v0.1.9", "0.2.0"))
        self.assertTrue(updates.newer("0.10.0", "0.9.9"))


if __name__ == "__main__":
    unittest.main()
