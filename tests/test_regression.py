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


class TestRemovedRegressionProductSurface(unittest.TestCase):
    """旧全局 regression runs API 已删除，不在测试中复活旧产品契约。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.led = Ledger(Path(cls.tmp.name) / "ata.sqlite")
        cls.led.append(parse_event(envelope("pi", "s1", "session.opened", {"title": "s1"},
                                           ts=1000, eid="open")))
        cls.httpd = make_server(cls.led, Path(cls.tmp.name), "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.led.close()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                body = json.load(exc)
            except ValueError:
                body = {}
            return exc.code, body

    def test_legacy_global_runs_route_is_unavailable(self):
        code, body = self.get("/api/runs")
        self.assertEqual(code, 404)
        self.assertFalse(body["ok"])

    def test_legacy_run_name_route_is_unavailable(self):
        code, body = self.get("/api/runs/r-1/name")
        self.assertEqual(code, 404)
        self.assertEqual(body, {})

    def test_run_reads_are_session_scoped(self):
        self.led.append(parse_event(envelope(
            "pi", "s1", "run.started",
            {"external_lifecycle_id": "ext-1", "boundary_source": "test"},
            run_id=1, ts=1001, eid="run")))
        code, body = self.get("/api/sessions/s1/runs")
        self.assertEqual(code, 200)
        self.assertEqual([run["run_id"] for run in body["runs"]], [1])


class TestScoreFactPreserved(unittest.TestCase):
    def test_session_score_remains_a_session_fact(self):
        opened = parse_event(envelope("pi", "s1", "session.opened", {"title": "s1"},
                                      ts=1000, eid="open"))
        score = parse_event(envelope("pi", "s1", "session.scored", {
            "value": "good", "note": "保留人工评分",
        }, ts=1001, eid="score"))
        projected = project_session("s1", "pi", [
            {"seq": 1, "event": opened}, {"seq": 2, "event": score},
        ])
        self.assertEqual(projected["scores"], [{
            "value": "good", "note": "保留人工评分", "ts": 1001,
        }])


if __name__ == "__main__":
    unittest.main()
