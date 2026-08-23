import unittest
from ata.plugins.pi import translate_hook


LINEAGE = {
    "PI_SUBAGENT_CHILD": "1",
    "PI_SUBAGENT_ORCHESTRATOR_SESSION_ID": "parent-abc",
    "PI_SUBAGENT_RUN_ID": "run-1",
    "PI_SUBAGENT_CHILD_AGENT": "scout",
    "PI_SUBAGENT_PARENT_DEPTH": "2",
}


def hook(name, event, state, **ctx):
    base = {"session_id": "s", "title": "s", "agent_id": "pi"}
    base.update(ctx)
    return translate_hook(name, event, base, state)


class TestLineageChannel(unittest.TestCase):
    def test_opened_carries_channel_parent_subagent(self):
        st = {}
        evs = hook("agent_start", {"timestamp": 1}, st,
                   channel="respond", lineage=LINEAGE)
        opened = [e for e in evs if e["type"] == "session.opened"][0]
        self.assertEqual(opened["payload"]["channel"], "respond")
        self.assertEqual(opened["payload"]["parent_session"], "parent-abc")
        sa = opened["payload"]["subagent"]
        self.assertEqual(sa["child_agent"], "scout")
        self.assertEqual(sa["depth"], "2")

    def test_absent_fields_omitted(self):
        st = {}
        evs = hook("agent_start", {"timestamp": 1}, st)
        opened = [e for e in evs if e["type"] == "session.opened"][0]
        for key in ("channel", "parent_session", "subagent"):
            self.assertNotIn(key, opened["payload"])


if __name__ == "__main__":
    unittest.main()
