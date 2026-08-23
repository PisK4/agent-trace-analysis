import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestDuration(unittest.TestCase):
    def test_tool_duration_from_ts_diff(self):
        st = {"opened": True, "turn": 1}
        hook("tool_execution_start",
             {"timestamp": 1000, "toolCallId": "c1", "toolName": "read", "args": {}}, st)
        evs = hook("tool_execution_end",
                   {"timestamp": 1250, "toolCallId": "c1", "toolName": "read",
                    "result": "ok", "isError": False}, st)
        end = [e for e in evs if e["type"] == "tool.upserted"][0]
        self.assertEqual(end["payload"]["duration_ms"], 250)


if __name__ == "__main__":
    unittest.main()
