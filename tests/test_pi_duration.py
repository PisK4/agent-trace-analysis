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

    def test_replay_without_start_writes_none_not_zero(self):
        # 会话重放只有 end 类事件、没有 start：耗时不可得应写 None（未测量），
        # 不能写 0（会被 timing 汇总当成实测零毫秒）
        st = {"opened": True, "turn": 1}
        evs = hook("message_end",
                   {"timestamp": 5000,
                    "message": {"role": "assistant",
                                "content": [{"type": "text", "text": "hi"}]}}, st,
                   session_id="r1")
        msg = [e for e in evs if e["type"] == "message.upserted"][0]
        self.assertIsNone(msg["payload"]["duration_ms"])
        evs = hook("tool_execution_end",
                   {"timestamp": 6000, "toolCallId": "c9", "toolName": "read",
                    "result": "ok", "isError": False}, st, session_id="r1")
        tool = [e for e in evs if e["type"] == "tool.upserted"][0]
        self.assertIsNone(tool["payload"]["duration_ms"])


if __name__ == "__main__":
    unittest.main()
