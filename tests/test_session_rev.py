import json, tempfile, threading, unittest
import urllib.request
from pathlib import Path
from ata.http import make_server
from ata.ledger import Ledger


def opened(sid):
    return {"v": 1, "id": f"{sid}:o", "agent_id": "pi", "session_id": sid,
            "ts": 1000, "type": "session.opened", "turn": None, "payload": {"title": sid}}


def message(sid, mid, turn=1):
    return {"v": 1, "id": mid, "agent_id": "pi", "session_id": sid,
            "ts": 1001 + turn, "type": "message.upserted", "turn": turn,
            "payload": {"message_id": mid, "role": "user", "text": "hi",
                        "started_at": 1000 + turn, "status": "completed"}}


class TestSessionRev(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.led = Ledger(cls.tmp / "t.sqlite")
        cls.led.append(opened("root"))
        cls.led.append(message("root", "m1"))
        cls.httpd = make_server(cls.led, cls.tmp, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, json.load(r)

    def test_full_page_carries_rev(self):
        code, out = self.get("/api/sessions/root")
        self.assertEqual(code, 200)
        self.assertNotIn("unchanged", out)
        self.assertEqual(out["rev"], self.led.session("root")["last_seq"])
        self.assertEqual([r["id"] for r in out["rows"]], ["m1"])

    def test_matching_rev_short_circuits(self):
        _, full = self.get("/api/sessions/root")
        code, out = self.get(f"/api/sessions/root?rev={full['rev']}")
        self.assertEqual(code, 200)
        self.assertEqual(out, {"ok": True, "unchanged": True, "rev": full["rev"]})

    def test_stale_rev_returns_page_with_new_rev(self):
        _, full = self.get("/api/sessions/root")
        self.led.append(message("root", "m2", turn=2))
        code, out = self.get(f"/api/sessions/root?rev={full['rev']}")
        self.assertEqual(code, 200)
        self.assertNotIn("unchanged", out)
        self.assertGreater(out["rev"], full["rev"])
        self.assertIn("m2", [r["id"] for r in out["rows"]])

    def test_no_rev_param_keeps_legacy_behavior(self):
        code, out = self.get("/api/sessions/root")
        self.assertEqual(code, 200)
        self.assertIn("rows", out)
        self.assertIn("has_older", out)
        self.assertIn("cursor", out)

    def test_bad_rev_falls_back_to_full_page(self):
        code, out = self.get("/api/sessions/root?rev=garbage")
        self.assertEqual(code, 200)
        self.assertIn("rows", out)


if __name__ == "__main__":
    unittest.main()
