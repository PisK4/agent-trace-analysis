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


class TestCollectTaskScoreFromConvenienceLayer(unittest.TestCase):
    """compare 的指标推导改吃便捷层端点（spec 定稿形状）。

    旧实现抓整页主投影在客户端重推 tool_fail_rate/tokens/duration，与
    summarize_* 的口径漂移（duration 含占位 1ms 行、tokens 行级 vs 逐轮）。
    新实现直接消费 /usage /tools /timing 的响应，口径纪律只在便捷层一份。
    """

    def collect(self, *, tools=None, usage=None, timing=None, scores=None, turns=3):
        return {
            r["name"]: r["value"]
            for r in collect_task_score(
                usage if usage is not None else {"turns": [], "total": {}, "missing_turns": 0},
                tools if tools is not None else {"tools": []},
                timing if timing is not None else {},
                (scores or [{"value": None}])[-1].get("value"),
                turns,
            )
        }

    def test_fail_rate_and_tokens_from_convenience_shapes(self):
        vals = self.collect(
            tools={"tools": [{"status": "failed"}, {"status": "completed"}]},
            usage={"turns": [
                {"status": "reported", "total_tokens": 120},
                {"status": "reported", "total_tokens": 80},
            ], "total": {}, "missing_turns": 0},
        )
        self.assertEqual(vals["tool_fail_rate"], 0.5)
        self.assertEqual(vals["tokens_reported"], 200)
        self.assertEqual(vals["usage_missing_turns"], 0)

    def test_missing_stays_missing_not_zero(self):
        vals = self.collect(
            usage={"turns": [{"status": "missing"}], "total": {}, "missing_turns": 1},
        )
        self.assertIsNone(vals["tokens_reported"])
        self.assertEqual(vals["usage_missing_turns"], 1)
        self.assertIsNone(vals["human_score"])
        self.assertIsNone(vals["tool_fail_rate"])   # 无工具调用即 missing

    def test_duration_excludes_placeholder_rows(self):
        # span 来自 summarize_timing（已排除占位），不再客户端拼 startedAt±durationMs
        vals = self.collect(timing={"span_ms": 1700})
        self.assertEqual(vals["duration_s"], 1.7)

    def test_span_missing_gives_none(self):
        vals = self.collect(timing={})
        self.assertIsNone(vals["duration_s"])


if __name__ == "__main__":
    unittest.main()
