import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestFullText(unittest.TestCase):
    def test_user_text_not_truncated(self):
        long = "字" * 500
        st = {"opened": True, "turn": 0}
        hook("agent_start", {"timestamp": 1}, st)
        evs = hook("message_start", {"timestamp": 2,
                   "message": {"role": "user", "content": long}}, st)
        texts = [e["payload"]["text"] for e in evs if e["type"] == "message.upserted"]
        self.assertTrue(texts and len(texts[0]) == 500)


if __name__ == "__main__":
    unittest.main()
