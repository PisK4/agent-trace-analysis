import json, tempfile, threading, unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger


def opened(sid, ts=1000):
    return {"v": 1, "id": f"{sid}:o", "agent_id": "pi", "session_id": sid,
            "ts": ts, "type": "session.opened", "turn": None,
            "payload": {"title": f"title-{sid}"}}


def scored(sid, value="good", note=None, ts=1001, eid=None):
    return {"v": 1, "id": eid or f"{sid}:s:{ts}", "agent_id": "pi", "session_id": sid,
            "ts": ts, "type": "session.scored", "turn": None,
            "payload": {"value": value, **({"note": note} if note else {})}}


def assigned(sid, run_id="r-1", task_id="t-1", ts=1002):
    return {"v": 1, "id": f"{sid}:a:{ts}", "agent_id": "pi", "session_id": sid,
            "ts": ts, "type": "session.assigned", "turn": None,
            "payload": {"run_id": run_id, "task_id": task_id}}


class AnnotationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = Ledger(self.tmp / "t.sqlite")

    def test_latest_score_wins_and_cleared_removes(self):
        self.led.append(opened("s1"))
        self.led.append(scored("s1", "bad", note="x"))
        self.led.append(scored("s1", "good", ts=1003))
        ann = self.led.annotations()
        self.assertEqual(len(ann["scores"]), 1)
        self.assertEqual(ann["scores"][0]["value"], "good")
        self.led.append({"v": 1, "id": "c1", "agent_id": "pi", "session_id": "s1",
                        "ts": 1004, "type": "session.score.cleared", "turn": None,
                        "payload": {}})
        self.assertEqual(self.led.annotations()["scores"], [])

    def test_unassigned_tombstone_scoped_to_run(self):
        self.led.append(opened("s1"))
        self.led.append(assigned("s1", run_id="r-1", task_id="t-1"))
        self.led.append(assigned("s1", run_id="r-2", task_id="t-2", ts=1003))
        self.assertEqual(len(self.led.annotations()["assignments"]), 2)
        self.led.append({"v": 1, "id": "u1", "agent_id": "pi", "session_id": "s1",
                        "ts": 1004, "type": "session.unassigned", "turn": None,
                        "payload": {"run_id": "r-1"}})
        ann = self.led.annotations()
        self.assertEqual([a["run_id"] for a in ann["assignments"]], ["r-2"])

    def test_annotations_carry_session_meta(self):
        self.led.append(opened("s1"))
        self.led.append({"v": 1, "id": "t1", "agent_id": "pi", "session_id": "s1",
                        "ts": 1001, "type": "tool.upserted", "turn": 1,
                        "payload": {"tool_call_id": "c1", "name": "Bash",
                                    "status": "failed"}})
        self.led.append(scored("s1", "bad", note="n"))
        row = self.led.annotations()["scores"][0]
        self.assertEqual(row["title"], "title-s1")
        self.assertEqual(row["agent"], "pi")
        self.assertEqual(row["event_count"], 3)
        self.assertEqual(row["error_count"], 1)

    def test_scores_sorted_desc_by_ts(self):
        self.led.append(opened("a"))
        self.led.append(opened("b"))
        self.led.append(scored("a", ts=1001))
        self.led.append(scored("b", ts=2001))
        self.assertEqual([s["session_id"] for s in self.led.annotations()["scores"]],
                         ["b", "a"])


class RenameTest(unittest.TestCase):
    def test_rename_updates_index_and_survives_reopen(self):
        tmp = Path(tempfile.mkdtemp())
        led = Ledger(tmp / "t.sqlite")
        led.append(opened("s1"))
        led.append({"v": 1, "id": "r1", "agent_id": "pi", "session_id": "s1",
                    "ts": 1005, "type": "session.renamed", "turn": None,
                    "payload": {"title": "我的名字"}})
        self.assertEqual(led.session("s1")["title"], "我的名字")
        # 后到的 opened（宿主重放）不得覆盖用户改名
        led.append(opened("s1", ts=1006))
        self.assertEqual(led.session("s1")["title"], "我的名字")


class TitleRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.led = Ledger(cls.tmp / "t.sqlite")
        cls.led.append(opened("s1"))
        cls.httpd = make_server(cls.led, cls.tmp, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(), method="POST",
            headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.load(r)

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

    def test_annotations_route(self):
        self.led.append(scored("s1", ts=1001))
        out = self.get("/api/annotations")
        self.assertEqual(out["ok"], True)
        self.assertEqual(out["scores"][0]["session_id"], "s1")
        self.assertEqual(out["assignments"], [])


if __name__ == "__main__":
    unittest.main()

class RunNameTest(unittest.TestCase):
    """组名 = runs.description：可改可清空（清空回退显示 run_id），run_id 不变。"""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.led = Ledger(cls.tmp / "t.sqlite")
        cls.led.create_run("r-abc", "旧组名")
        cls.httpd = make_server(cls.led, cls.tmp, "127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(), method="POST",
            headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.load(e)

    def test_rename_run(self):
        code, out = self.post("/api/runs/r-abc/name", {"name": "中文组名 English"})
        self.assertEqual(code, 200)
        self.assertEqual(self.led.run("r-abc")["description"], "中文组名 English")

    def test_clear_name_and_unknown_run(self):
        code, out = self.post("/api/runs/r-abc/name", {"name": ""})
        self.assertEqual(code, 200)  # 清空允许：回退显示 run_id
        self.assertEqual(self.led.run("r-abc")["description"], "")
        code, _ = self.post("/api/runs/r-nope/name", {"name": "x"})
        self.assertEqual(code, 404)
