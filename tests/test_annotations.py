import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.project import project_session
from ata.schema import envelope, parse_event


def opened(sid, ts=1000):
    return parse_event(envelope("pi", sid, "session.opened", {"title": f"title-{sid}"}, ts=ts,
                                      eid=f"{sid}:o"))


def scored(sid, value="good", note=None, ts=1001, eid=None):
    payload = {"value": value}
    if note:
        payload["note"] = note
    return parse_event(envelope("pi", sid, "session.scored", payload, ts=ts,
                                      eid=eid or f"{sid}:s:{ts}"))


class AnnotationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = Ledger(Path(self.tmp.name) / "ata.sqlite")

    def tearDown(self):
        self.led.close()
        self.tmp.cleanup()

    def scores(self, sid):
        meta = self.led.session(sid)
        return project_session(sid, meta["agent"], self.led.read(sid))["scores"]

    def test_latest_score_wins_and_cleared_removes(self):
        self.led.append(opened("s1"))
        self.led.append(scored("s1", "bad", note="x"))
        self.led.append(scored("s1", "good", ts=1003))
        scores = self.scores("s1")
        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[-1]["value"], "good")
        self.led.append(parse_event(envelope(
            "pi", "s1", "session.score.cleared", {}, ts=1004, eid="c1")))
        self.assertEqual(self.scores("s1"), [])

    def test_score_is_a_session_fact_with_session_meta(self):
        self.led.append(opened("s1"))
        self.led.append(parse_event(envelope(
            "pi", "s1", "tool.upserted", {
                "tool_call_id": "c1", "name": "Bash", "status": "failed", "started_at": 1001,
            }, observed_turn_ordinal=1, ts=1001, eid="t1")))
        self.led.append(scored("s1", "bad", note="n"))
        projected = project_session("s1", "pi", self.led.read("s1"))
        self.assertEqual(projected["title"], "title-s1")
        self.assertEqual(projected["scores"][-1]["value"], "bad")
        self.assertEqual(projected["rows"][-1]["status"], "failed")

    def test_scores_sorted_by_event_ts(self):
        self.led.append(opened("a"))
        self.led.append(opened("b"))
        self.led.append(scored("a", ts=1001))
        self.led.append(scored("b", ts=2001))
        self.assertEqual([s["ts"] for s in self.scores("a")], [1001])
        self.assertEqual([s["ts"] for s in self.scores("b")], [2001])


class TitleRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.led = Ledger(Path(cls.tmp.name) / "ata.sqlite")
        cls.led.append(opened("s1"))
        cls.httpd = make_server(cls.led, Path(cls.tmp.name), "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.led.close()
        cls.tmp.cleanup()

    def post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
            method="POST", headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return json.load(response)

    def test_rename_route(self):
        code, out = self.post("/api/sessions/s1/title", {"title": "新标题"})
        self.assertEqual(code, 200)
        self.assertEqual(out["title"], "新标题")
        self.assertEqual(self.led.session("s1")["title"], "新标题")
        self.assertEqual(self.get("/api/sessions/s1")["title"], "新标题")

    def test_rename_validation(self):
        code, _ = self.post("/api/sessions/s1/title", {"title": "  "})
        self.assertEqual(code, 400)
        code, _ = self.post("/api/sessions/nope/title", {"title": "x"})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
