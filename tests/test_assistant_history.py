"""The model must remember tool calls + results on the next turn (regression:
they used to live only inside the engine and were lost after each reply)."""

from friday.assistant import Assistant
from friday.config import Settings
from friday.llm.base import TextDelta, ToolActivity
from friday.skills.registry import SkillRegistry


class FakeEngine:
    """Emits one tool round-trip then some text, like the real engine."""

    def stream(self, messages, tools=None, out_history=None):
        yield ToolActivity(name="web_search", arguments='{"q": "weather"}')
        if out_history is not None:
            out_history.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "web_search", "arguments": '{"q": "weather"}'},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_1", "content": '{"result": "sunny"}'},
                ]
            )
        yield TextDelta(text="It is sunny today.")


def test_tool_round_trips_persist_in_history():
    a = Assistant(Settings(), FakeEngine(), SkillRegistry())
    list(a.ask("what's the weather?"))

    roles = [m["role"] for m in a.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert a.messages[2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert "sunny" in a.messages[3]["content"]
    assert a.messages[4]["content"] == "It is sunny today."


def test_reset_keeps_system_prompt():
    a = Assistant(Settings(), FakeEngine(), SkillRegistry())
    list(a.ask("hello"))
    a.reset()
    assert len(a.messages) == 1 and a.messages[0]["role"] == "system"
