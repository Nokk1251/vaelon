import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["VAELON_HOME"] = tempfile.mkdtemp()

from vaelon.agent import Agent
from vaelon.config import Config
from vaelon.memory import Memory
from vaelon.structured import AnswerStreamer, tool_schema


def stream_all(text, size=3):
    s, out = AnswerStreamer(), ""
    for i in range(0, len(text), size):
        out += s.feed(text[i:i + size])
    return out


class Streamer(unittest.TestCase):
    def test_streams_answer_only_when_tool_none(self):
        self.assertEqual(stream_all('{"tool": "none", "args": {}, "answer": "Hello, Boss."}'), "Hello, Boss.")

    def test_streams_when_answer_comes_first(self):
        # Ollama often emits keys alphabetically: the answer must still stream immediately
        self.assertEqual(stream_all('{ "answer": "Hi there.", "args": {}, "tool": "none" }'), "Hi there.")

    def test_never_streams_tool_calls(self):
        self.assertEqual(stream_all('{"tool": "now", "args": {}, "answer": "secret plan"}'), "")

    def test_escapes_and_unicode(self):
        self.assertEqual(stream_all('{"tool":"none","args":{},"answer":"a\\"b\\nc \\u0416\\u0438\\u0432"}', 2), 'a"b\nc Жив')

    def test_stops_at_closing_quote(self):
        self.assertEqual(stream_all('{"tool":"none","args":{},"answer":"hi"} trailing "x"'), "hi")


class FakeOllama:
    """Pretends to be Ollama with schema support; records the schema it was given."""
    supports_schema = True

    def __init__(self, replies):
        self.replies, self.schemas = list(replies), []

    def chat_stream(self, msgs, fmt=None):
        self.schemas.append(fmt)
        r = self.replies.pop(0)
        for i in range(0, len(r), 4):
            yield r[i:i + 4]

    def chat(self, msgs, fmt=None):
        return "".join(self.chat_stream(msgs, fmt))


class SchemaAgent(unittest.TestCase):
    def agent(self, llm):
        return Agent(Config(provider="mock"), llm=llm, memory=Memory(":memory:"), load_extensions=False)

    def test_answer_streams_and_schema_restricts_tools(self):
        llm = FakeOllama(['{"tool": "none", "args": {}, "answer": "Готово, Boss."}'])
        ev = []
        out = self.agent(llm).run("кажи нещо", on_event=lambda k, d: ev.append((k, d)))
        self.assertEqual(out, "Готово, Boss.")
        self.assertEqual("".join(d for k, d in ev if k == "token"), "Готово, Boss.")
        enum = llm.schemas[0]["properties"]["tool"]["enum"]
        self.assertIn("now", enum)
        self.assertIn("none", enum)

    def test_tool_then_answer(self):
        llm = FakeOllama(['{"tool": "system_info", "args": {}, "answer": ""}',
                          '{"tool": "none", "args": {}, "answer": "OK"}'])
        ev = []
        out = self.agent(llm).run("how is my pc doing", on_event=lambda k, d: ev.append((k, d)))
        self.assertEqual(out, "OK")
        self.assertEqual([d for k, d in ev if k == "tool"], ["system_info"])
        self.assertEqual("".join(d for k, d in ev if k == "token"), "OK")

    def test_schema_enum_helper(self):
        self.assertEqual(tool_schema(["b", "a"])["properties"]["tool"]["enum"], ["a", "b", "none"])


class CloudToolCalling(unittest.TestCase):
    """Cloud models use native function calling; their calls become Vaelon's {"tool","args"} JSON."""

    def test_native_call_and_reasoning_rescue(self):
        import json

        from vaelon.llm import _from_reasoning, _tool_json

        self.assertEqual(json.loads(_tool_json("stock_quote", '{"symbol": "^GSPC"}')),
                         {"tool": "stock_quote", "args": {"symbol": "^GSPC"}})
        self.assertEqual(json.loads(_tool_json("now", "not json")), {"tool": "now", "args": {}})
        hidden = 'We should call it.{"tool": "stock_quote", "args": {"symbol": "^GSPC"}}'
        self.assertTrue(_from_reasoning(hidden).startswith('{"tool"'))
        self.assertEqual(_from_reasoning("just private thoughts"), "")  # never leak the reasoning itself

    def test_specs_and_lean_prompt(self):
        from vaelon.tools import registry

        registry.load_builtin()
        spec = registry.openai_tools(["stock_quote"])[0]["function"]
        self.assertEqual(spec["parameters"]["required"], ["symbol"])
        self.assertIn("days", spec["parameters"]["properties"])

        class Cloud:
            supports_tools = True
            seen = None

            def chat(self, messages, tools=None):
                Cloud.seen = (messages, tools)
                return "Hello."

        a = Agent(Config(provider="mock"), llm=Cloud(), memory=Memory(":memory:"), load_extensions=False)
        self.assertEqual(a.run("hi"), "Hello.")
        msgs, tools = Cloud.seen
        self.assertTrue(tools)  # tools travel as native specs...
        self.assertNotIn("TOOLS\n", msgs[0]["content"])  # ...not a second time as text

    def test_empty_answer_never_kept(self):
        class Empty:
            def chat(self, messages):
                return ""

        a = Agent(Config(provider="mock"), llm=Empty(), memory=Memory(":memory:"), load_extensions=False)
        out = a.run("What is the state of things?")
        self.assertTrue(out.strip())  # the user gets a message, not silence
        self.assertTrue(all(m["content"].strip() for m in a.history))


if __name__ == "__main__":
    unittest.main()
