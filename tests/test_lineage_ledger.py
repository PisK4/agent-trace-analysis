import tempfile, unittest
from pathlib import Path
from ata.ledger import Ledger


def opened_ev(sid, title="t", parent=None):
    payload = {"title": title}
    if parent:
        payload["parent_session"] = parent
    return {"v": 1, "id": f"{sid}:opened", "agent_id": "pi", "session_id": sid,
            "ts": 1000, "type": "session.opened", "observed_turn_ordinal": None, "payload": payload}


class TestLineage(unittest.TestCase):
    def setUp(self):
        self.led = Ledger(Path(tempfile.mkdtemp()) / "t.sqlite")

    def tearDown(self):
        self.led.close()

    def test_parent_captured_on_open(self):
        self.led.append(opened_ev("child", parent="parent-1"))
        self.assertEqual(self.led.session("child")["parent_session_id"], "parent-1")

    def test_children_and_ancestry(self):
        self.led.append(opened_ev("root"))
        self.led.append(opened_ev("mid", parent="root"))
        self.led.append(opened_ev("leaf", parent="mid"))
        kids = self.led.children("root")
        self.assertEqual([r["id"] for r in kids], ["mid"])
        chain = self.led.ancestry("leaf")
        self.assertEqual([r["id"] for r in chain], ["mid", "root"])

    def test_no_parent_is_none_and_empty(self):
        self.led.append(opened_ev("solo"))
        self.assertIsNone(self.led.session("solo")["parent_session_id"])
        self.assertEqual(self.led.children("solo"), [])


if __name__ == "__main__":
    unittest.main()
