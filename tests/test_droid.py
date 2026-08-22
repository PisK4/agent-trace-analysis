import json
import tempfile
import unittest
from pathlib import Path
from ata.plugins.droid import translate_file, translate_line, refresh_titles
from ata.project import project_session

class DroidTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertIn("turn.ended", types)
        self.assertIn("compaction.boundary", types)
        compact = next(e for e in evs if e["type"] == "compaction.boundary")
        self.assertEqual(compact["payload"]["trigger"], "llm_summary")
        self.assertEqual(compact["payload"]["removed_count"], 3)
        # 标题来自 session_start.title（v2 形状）
        titles = [e["payload"]["title"] for e in evs if e["type"] == "session.opened"]
        self.assertEqual(titles[0], "open first-party jsonl")
        recs = [{"seq": i+1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("droid-missing", "droid", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["usage"]["status"], "missing")
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["name"], "Read")
        compacted = next(r for r in sess["rows"] if r["kind"] == "compacted")
        self.assertEqual(compacted["tag"], "COMPACTED")
        self.assertIn("removed 3", compacted["note"])

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

    def test_v1_top_level_shape_compat(self):
        # 2026-08-16 审计：~/.factory/sessions 的 v2 形状把消息嵌套在 `message` 字段；
        # 更早的 marketplace 样本把 role/content 放顶层。两层都要翻译。
        raw = {"type": "message", "id": "x1", "role": "user",
               "content": [{"type": "text", "text": "hi"}]}
        evs = translate_line(raw, {})
        hit = [e for e in evs if e["type"] == "message.upserted" and e["payload"]["text"] == "hi"]
        self.assertTrue(hit)

    def test_context_does_not_start_turn(self):
        state = {}
        evs = []
        evs += translate_line({"type": "message", "id": "u1", "role": "user",
                               "content": [{"type": "text", "text": "hello"}]}, state)
        evs += translate_line({"type": "message", "id": "c1", "role": "user",
                               "content": [{"type": "text", "text": "<system-reminder>tools"}]}, state)
        turns = [e for e in evs if e["type"] == "turn.started"]
        self.assertEqual(len(turns), 1)
        ctx = [e for e in evs if e["type"] == "message.upserted" and e["payload"]["message_id"] == "c1"][0]
        self.assertEqual(ctx["turn"], 1)

    def test_thinking_split_from_text(self):
        # 对标 dsh 的 thinking 折叠：thinking 块不再并入正文本，
        # 单独进 payload["thinking"]，text 只保留正文，前端折叠展示。
        raw = {"type": "message", "id": "x2",
               "message": {"role": "assistant", "content": [
                   {"type": "thinking", "thinking": "planning..."},
                   {"type": "text", "text": "answer"},
               ]}}
        evs = translate_line(raw, {})
        msg = [e for e in evs if e["type"] == "message.upserted"][-1]
        self.assertEqual(msg["payload"]["text"], "answer")
        self.assertEqual(msg["payload"]["thinking"], "planning...")

    def test_refresh_titles_fixes_placeholder_and_skips_titled(self):
        # 回归：Droid 首条消息后才生成真实标题并原地重写 session_start 行，
        # tail 按偏移读不到，账本里永远留着 "New Session"。refresh_titles 按
        # 文件首行纠正占位标题；已命名的会话整轮跳过。
        from ata.ledger import Ledger
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            renamed, still_new = root / "sid-1.jsonl", root / "sid-2.jsonl"
            renamed.write_text(json.dumps(
                {"type": "session_start", "id": "sid-1", "title": "真实标题"}) + "\n")
            still_new.write_text(json.dumps(
                {"type": "session_start", "id": "sid-2", "title": "New Session"}) + "\n")
            led = Ledger(root / "ledger.sqlite")
            for sid in ("sid-1", "sid-2"):
                led.append({"v": 1, "id": "o", "agent_id": "droid", "session_id": sid,
                            "ts": 1, "type": "session.opened", "turn": None,
                            "payload": {"title": "New Session"}})
            refresh_titles(root, led)
            self.assertEqual(led.session("sid-1")["title"], "真实标题")
            # 占位标题没被换成别的值；文件仍是 New Session 就保持原样
            self.assertEqual(led.session("sid-2")["title"], "New Session")
            # 详情页标题从事件流投影（后写覆盖），修正必须以 opened 事件落进事件流，
            # 否则列表已纠正、点开又打回 New Session。
            recs = led.read("sid-1")
            proj = project_session("sid-1", "droid", recs)
            self.assertEqual(proj["title"], "真实标题")
            # 幂等：同签名重复刷新不重复追加
            refresh_titles(root, led)
            self.assertEqual(len([r for r in led.read("sid-1")
                                  if r["event"]["type"] == "session.opened"]), 2)

    def test_refresh_fixes_stale_stream_even_if_table_corrected(self):
        # 回归：sessions 表标题曾被单独修正过（非占位值），但事件流里只有旧的
        # New Session。跳过判断不能拿表标题当代理，否则点开详情又打回原形。
        from ata.ledger import Ledger
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sid-9.jsonl").write_text(json.dumps(
                {"type": "session_start", "id": "sid-9", "title": "新标题"}) + "\n")
            led = Ledger(root / "ledger.sqlite")
            led.append({"v": 1, "id": "o", "agent_id": "droid", "session_id": "sid-9",
                        "ts": 1, "type": "session.opened", "turn": None,
                        "payload": {"title": "New Session"}})
            led._lock.acquire()
            led._conn.execute("UPDATE sessions SET title='手工修正过' WHERE session_id='sid-9'")
            led._conn.commit()
            led._lock.release()
            refresh_titles(root, led)
            proj = project_session("sid-9", "droid", led.read("sid-9"))
            self.assertEqual(proj["title"], "新标题")

    def test_refresh_skips_sessions_not_in_ledger(self):
        # 账本里不存在的会话不凭空建行，否则 tail 窗口外的历史文件会以空壳涌进列表。
        from ata.ledger import Ledger
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ghost.jsonl").write_text(json.dumps(
                {"type": "session_start", "id": "ghost", "title": "幽灵"}) + "\n")
            led = Ledger(root / "ledger.sqlite")
            refresh_titles(root, led)
            self.assertIsNone(led.session("ghost"))

    def test_cancelled_outcome_marks_assistant(self):
        state = {}
        evs = []
        evs += translate_line({"type": "message", "id": "u1", "role": "user",
                               "content": [{"type": "text", "text": "hello"}]}, state)
        evs += translate_line({"type": "message", "id": "a1",
                               "message": {"role": "assistant", "content": [
                                   {"type": "text", "text": "working"},
                               ]}}, state)
        evs += translate_line({"type": "agent_turn_outcome", "turnId": "t1",
                               "reason": "cancelled", "resultKind": "null"}, state)
        recs = [{"seq": i + 1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("droid-session", "droid", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["status"], "cancelled")

if __name__ == "__main__":
    unittest.main()
