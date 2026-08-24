import json, tempfile, threading, unittest
import urllib.request
from pathlib import Path
from ata.http import make_server
from ata.ledger import Ledger


def opened(sid, parent=None):
    payload = {"title": sid}
    if parent:
        payload["parent_session"] = parent
    return {"v": 1, "id": f"{sid}:o", "agent_id": "pi", "session_id": sid,
            "ts": 1000, "type": "session.opened", "turn": None, "payload": payload}


class TestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.led = Ledger(cls.tmp / "t.sqlite")
        cls.led.append(opened("root"))
        cls.led.append(opened("kid", parent="root"))
        cls.led.append({"v": 1, "id": "m1", "agent_id": "pi", "session_id": "root",
                        "ts": 1001, "type": "message.upserted", "turn": 1,
                        "payload": {"message_id": "m1", "role": "user", "text": "hi",
                                    "status": "completed"}})
        cls.httpd = make_server(cls.led, cls.tmp, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def test_events_cursor(self):
        code, out = self.get("/api/sessions/root/events?after_seq=1&limit=10")
        self.assertEqual(code, 200)
        self.assertEqual(out["ok"], True)
        self.assertEqual([e["seq"] for e in out["events"]], [2])
        self.assertEqual(out["next_after_seq"], 2)

    def test_events_unknown_session_404(self):
        code, out = self.get("/api/sessions/nope/events")
        self.assertEqual(code, 404)
        self.assertEqual(out["error"], "unknown session")

    def test_lineage_empty_is_ok(self):
        code, out = self.get("/api/sessions/root/lineage")
        self.assertEqual(code, 200)
        self.assertEqual(out["ancestors"], [])
        # kid 在 fixture 里以 root 为父，root 的 children 必含 kid
        self.assertEqual([c["id"] for c in out["children"]], ["kid"])
        code, out = self.get("/api/sessions/kid/lineage")
        self.assertEqual([a["id"] for a in out["ancestors"]], ["root"])

    def test_convenience_endpoints(self):
        led_events = [
            {"v": 1, "id": "u1", "agent_id": "pi", "session_id": "conv",
             "ts": 10, "type": "message.upserted", "turn": 1,
             "payload": {"message_id": "a1", "role": "assistant", "text": "done",
                         "status": "completed", "model": "m",
                         "usage": {"status": "reported", "input": 10, "output": 2,
                                   "cache_read": 0, "cache_write": 0,
                                   "total_tokens": 12, "cost": None}}},
            {"v": 1, "id": "t1", "agent_id": "pi", "session_id": "conv",
             "ts": 11, "type": "tool.upserted", "turn": 1,
             "payload": {"tool_call_id": "c1", "name": "read", "status": "failed",
                         "result": "EACCES", "duration_ms": 5}},
        ]
        self.__class__.led.append(opened("conv"))
        for e in led_events:
            self.__class__.led.append(e)
        code, out = self.get("/api/sessions/conv/usage")
        self.assertEqual(code, 200)
        self.assertEqual(out["total"]["total_tokens"], 12)
        self.assertEqual(out["turns"][0]["model"], "m")
        code, out = self.get("/api/sessions/conv/tools?status=failed")
        self.assertEqual(out["tools"][0]["result"], "EACCES")
        code, out = self.get("/api/sessions/conv/tool-stats")
        self.assertEqual(code, 200)
        self.assertEqual(out["summary"]["calls"], 1)
        self.assertEqual(out["summary"]["failed"], 1)
        self.assertEqual(out["summary"]["mounted"], None)  # 会话无目录，使用率 n/a
        self.assertEqual(out["tools"][0]["name"], "read")
        self.assertEqual(out["tools"][0]["calls"][0]["status"], "failed")
        code, out = self.get("/api/sessions/nope/tool-stats")
        self.assertEqual(code, 404)
        code, out = self.get("/api/sessions/conv/compactions")
        self.assertEqual(out["compactions"], [])


if __name__ == "__main__":
    unittest.main()
