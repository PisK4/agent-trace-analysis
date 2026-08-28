import unittest

from ata.plugins.pi import translate_hook


def hook(name, event, st=None):
    st = st if st is not None else {"opened": True, "observed_turn_ordinal": 1}
    return translate_hook(name, event, {"session_id": "s1"}, st)


class AssistantModelTests(unittest.TestCase):
    def test_message_end_carries_model_and_provider(self):
        evs = hook("message_end", {
            "timestamp": 9,
            "message": {
                "role": "assistant", "model": "kimi-k2", "provider": "moonshot",
                "stopReason": "stop",
                "usage": {"input": 10, "output": 5, "totalTokens": 15},
                "content": [{"type": "text", "text": "hi"}],
            },
        })
        up = [e for e in evs if e["type"] == "message.upserted"][0]
        self.assertEqual(up["payload"]["model"], "kimi-k2")
        self.assertEqual(up["payload"]["provider"], "moonshot")

    def test_user_rows_have_null_model_and_provider(self):
        evs = hook("message_end", {
            "timestamp": 9, "message": {"role": "user", "content": "q"},
        })
        up = [e for e in evs if e["type"] == "message.upserted"][0]
        self.assertIsNone(up["payload"]["model"])
        self.assertIsNone(up["payload"]["provider"])

    def test_turn_end_reupsert_carries_model_and_provider(self):
        st = {"opened": True, "observed_turn_ordinal": 1, "last_assistant_id": "a1", "request_no": 1}
        evs = hook("turn_end", {
            "timestamp": 11,
            "message": {
                "role": "assistant", "responseId": "a1",
                "model": "kimi-k2", "provider": "moonshot", "stopReason": "stop",
                "usage": {"input": 1, "output": 2},
                "content": [{"type": "text", "text": "final"}],
            },
        }, st)
        re_up = [e for e in evs if e["type"] == "message.upserted"]
        self.assertEqual(re_up[0]["payload"]["model"], "kimi-k2")
        self.assertEqual(re_up[0]["payload"]["provider"], "moonshot")

    def test_turn_ended_payload_carries_model_and_provider(self):
        st = {"opened": True, "observed_turn_ordinal": 1}
        evs = hook("turn_end", {
            "timestamp": 11,
            "message": {"role": "assistant", "responseId": "a1",
                        "model": "kimi-k2", "provider": "moonshot",
                        "stopReason": "stop", "usage": {"input": 1, "output": 2}},
        }, st)
        ended = [e for e in evs if e["type"] == "turn.ended"][0]
        self.assertEqual(ended["payload"]["model"], "kimi-k2")
        self.assertEqual(ended["payload"]["provider"], "moonshot")


if __name__ == "__main__":
    unittest.main()
