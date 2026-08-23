import unittest
from ata.plugins.pi import translate_hook


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestTurnStatus(unittest.TestCase):
    def test_aborted_maps_to_cancelled(self):
        st = {"opened": True, "turn": 1}
        evs = hook("turn_end", {"timestamp": 9,
                   "message": {"role": "assistant", "stopReason": "aborted"}}, st)
        ended = [e for e in evs if e["type"] == "turn.ended"][0]
        self.assertEqual(ended["payload"]["status"], "cancelled")

    def test_normal_end_has_no_status_key(self):
        st = {"opened": True, "turn": 1}
        evs = hook("turn_end", {"timestamp": 9,
                   "message": {"role": "assistant", "stopReason": "stop"}}, st)
        ended = [e for e in evs if e["type"] == "turn.ended"][0]
        self.assertNotIn("status", ended["payload"])


if __name__ == "__main__":
    unittest.main()
