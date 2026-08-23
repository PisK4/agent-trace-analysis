import tempfile
import unittest
from pathlib import Path

from ata.cli import collect_task_score
from ata.ledger import Ledger
from ata.schema import parse_event, ValidationError


def assigned(run_id="r-1", task_id="t-1", turn=None):
    return {"v": 1, "id": "x1", "agent_id": "cue", "session_id": "s1",
            "ts": 1000, "type": "session.assigned", "turn": turn,
            "payload": {"run_id": run_id, "task_id": task_id}}


class TestAssignedSchema(unittest.TestCase):
    def test_accepts_valid(self):
        ev = parse_event(assigned())
        self.assertEqual(ev["type"], "session.assigned")
        self.assertIsNone(ev["turn"])

    def test_rejects_missing_run_id(self):
        raw = assigned()
        raw["payload"] = {"task_id": "t-1"}
        with self.assertRaises(ValidationError):
            parse_event(raw)

    def test_rejects_empty_task_id(self):
        with self.assertRaises(ValidationError):
            parse_event(assigned(task_id=""))

    def test_rejects_turn(self):
        with self.assertRaises(ValidationError):
            parse_event(assigned(turn=2))


class TestRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.led = Ledger(Path(self.tmp.name))

    def tearDown(self):
        self.led.close()
        self.tmp.cleanup()

    def test_create_and_duplicate(self):
        self.led.create_run("r-1", "改了提示词", fp := "abc", ts=123)
        run = self.led.run("r-1")
        self.assertEqual(run["description"], "改了提示词")
        self.assertEqual(run["taskset_fingerprint"], "abc")
        with self.assertRaises(ValueError):
            self.led.create_run("r-1", "重复")

    def test_runs_ordering_and_unknown(self):
        self.led.create_run("r-2", "b", ts=200)
        self.led.create_run("r-1", "a", ts=100)
        self.assertEqual([r["run_id"] for r in self.led.runs()], ["r-1", "r-2"])
        self.assertIsNone(self.led.run("nope"))

    def test_assign_events_roundtrip(self):
        self.led.append(parse_event(assigned(run_id="r-1")))
        second = assigned(run_id="r-2", task_id="t-9")
        second["id"] = "x2"
        second["session_id"] = "s2"
        self.led.append(parse_event(second))
        got = {(a["session_id"], a["run_id"], a["task_id"])
               for a in self.led.assign_events()}
        self.assertEqual(got, {("s1", "r-1", "t-1"), ("s2", "r-2", "t-9")})


class TestCollectTaskScore(unittest.TestCase):
    def proj(self, rows, turns=3, scores=None):
        return {"rows": rows, "turns": turns, "scores": scores or []}

    def row(self, kind, status="completed", usage=None, started=0, dur=0):
        r = {"kind": kind, "status": status, "startedAt": started,
             "durationMs": dur}
        if kind == "assistant":
            r["usage"] = usage
        return r

    def names(self, records):
        return {r["name"]: r["value"] for r in records}

    def test_full_data(self):
        rows = [
            self.row("tool", status="failed"),
            self.row("tool"),
            self.row("assistant", usage={"status": "reported", "totalTokens": 120},
                     started=1000, dur=500),
            self.row("assistant", usage={"status": "reported", "totalTokens": 80},
                     started=2000, dur=700),
        ]
        vals = self.names(collect_task_score(
            self.proj(rows, scores=[{"value": "bad"}])))
        self.assertEqual(vals["human_score"], "bad")
        self.assertEqual(vals["turns"], 3)
        self.assertEqual(vals["tool_fail_rate"], 0.5)
        self.assertEqual(vals["tokens_reported"], 200)
        self.assertEqual(vals["usage_missing_turns"], 0)
        self.assertEqual(vals["duration_s"], 1.7)

    def test_missing_stays_missing_not_zero(self):
        rows = [self.row("assistant", usage={"status": "missing"})]
        vals = self.names(collect_task_score(self.proj(rows)))
        self.assertIsNone(vals["tokens_reported"])   # 缺失不当 0
        self.assertEqual(vals["usage_missing_turns"], 1)
        self.assertIsNone(vals["human_score"])
        self.assertIsNone(vals["tool_fail_rate"])    # 无工具调用即 missing
        self.assertIsNone(vals["duration_s"])        # 单行无法算时长

    def test_empty_projection(self):
        vals = self.names(collect_task_score(self.proj([])))
        for name in ("turns", "tokens_reported", "usage_missing_turns"):
            self.assertIn(name, vals)


if __name__ == "__main__":
    unittest.main()
