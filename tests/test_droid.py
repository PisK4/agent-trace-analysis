import unittest
from pathlib import Path
from ata.plugins.droid import translate_file
from ata.project import project_session

class DroidTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertIn("turn.ended", types)
        self.assertNotIn("compaction.boundary", types)
        recs = [{"seq": i+1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("droid-missing", "droid", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["usage"]["status"], "missing")
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["name"], "Read")

    def test_tool_start_end_ids_differ(self):
        # 回归：tool_use 与 tool_result 曾共用 event id，幂等账本吞掉完成态
        # 导致工具行永远 pending。两者必须拆成 :start / :end。
        evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        tool_events = [e for e in evs if e["type"] == "tool.upserted"]
        self.assertEqual(len(tool_events), 2)
        self.assertTrue(tool_events[0]["id"].endswith(":start"))
        self.assertTrue(tool_events[1]["id"].endswith(":end"))
        self.assertNotEqual(tool_events[0]["id"], tool_events[1]["id"])
        self.assertEqual(tool_events[0]["payload"]["tool_call_id"],
                         tool_events[1]["payload"]["tool_call_id"])

    def test_tool_row_reaches_completed(self):
        # 回归：把翻译结果真走一遍账本（幂等按 id 去重）再投影，
        # 工具行必须是 completed 且带 result，而不是永远 pending。
        from ata.ledger import Ledger
        from ata.schema import parse_event
        import tempfile
        evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            for ev in evs:
                led.append(parse_event(ev))
            sess = project_session("droid-missing", "droid", led.read("droid-missing"))
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["status"], "completed")
        self.assertEqual(tool["result"], "type=message")
        self.assertIsNotNone(tool["parentId"])

if __name__ == "__main__":
    unittest.main()
