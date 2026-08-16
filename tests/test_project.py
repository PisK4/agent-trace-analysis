import unittest
from ata.project import project_session
from ata.schema import parse_event


def rec(seq, ev):
    return {"seq": seq, "event": parse_event(ev)}


class ProjectTest(unittest.TestCase):
    def test_usage_and_order(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","turn":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"ts","agent_id":"pi","session_id":"s","ts":2,"type":"turn.started","turn":1,"payload":{}}),
            rec(3, {"v":1,"id":"u","agent_id":"pi","session_id":"s","ts":3,"type":"message.upserted","turn":1,"payload":{
                "message_id":"u1","role":"user","text":"hello","status":"completed","request_no":None,
                "usage":None,"started_at":3,"duration_ms":10,"output_text":None}}),
            rec(4, {"v":1,"id":"a","agent_id":"pi","session_id":"s","ts":4,"type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":{"status":"reported","input":10,"output":2,"cache_read":1,"cache_write":0,"total_tokens":13,"cost":None},
                "started_at":4,"duration_ms":20,"output_text":"ok"}}),
            rec(5, {"v":1,"id":"t","agent_id":"pi","session_id":"s","ts":5,"type":"tool.upserted","turn":1,"payload":{
                "tool_call_id":"c1","parent_message_id":"a1","name":"Read","text":"f","status":"completed",
                "payload":{"path":"f"},"result":"ok","started_at":5,"duration_ms":5}}),
        ]
        sess = project_session("s", "pi", recs)
        kinds = [r["kind"] for r in sess["rows"]]
        self.assertEqual(kinds, ["user", "assistant", "tool"])
        self.assertTrue(sess["rows"][0]["start"])
        self.assertEqual(sess["rows"][1]["usage"]["cacheRead"], 1)
        # 适配器带 total_tokens/cost，投影层必须透传（此前丢失）。
        self.assertEqual(sess["rows"][1]["usage"]["totalTokens"], 13)
        self.assertIsNone(sess["rows"][1]["usage"]["cost"])
        self.assertEqual(sess["rows"][2]["parentId"], "a1")
        self.assertEqual(sess["rows"][2]["usage"]["status"], "n/a")
        self.assertEqual(sess["rows"][2]["text"], 'Read {"path":"f"}')

    def test_system_reminder_is_context(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","turn":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"u","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","turn":1,"payload":{
                "message_id":"u1","role":"user","text":"<system-reminder>The tools listed below are available",
                "status":"completed","request_no":None,"usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
        ]
        row = project_session("d", "droid", recs)["rows"][0]
        self.assertEqual(row["kind"], "context")
        self.assertEqual(row["tag"], "CONTEXT")
        self.assertFalse(row["start"])

    def test_context_does_not_open_turn(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","turn":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"u","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","turn":1,"payload":{
                "message_id":"u1","role":"user","text":"hello","status":"completed","request_no":None,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
            rec(3, {"v":1,"id":"c","agent_id":"droid","session_id":"d","ts":3,"type":"message.upserted","turn":2,"payload":{
                "message_id":"c1","role":"user","text":"<system-reminder>The tools listed below are available",
                "status":"completed","request_no":None,"usage":None,"started_at":3,"duration_ms":1,"output_text":None}}),
            rec(4, {"v":1,"id":"a","agent_id":"droid","session_id":"d","ts":4,"type":"message.upserted","turn":2,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":None,"started_at":4,"duration_ms":1,"output_text":"ok"}}),
        ]
        rows = project_session("d", "droid", recs)["rows"]
        self.assertEqual([r["kind"] for r in rows], ["user", "context", "assistant"])
        self.assertEqual(rows[0]["turn"], 1)
        self.assertTrue(rows[0]["start"])
        self.assertEqual(rows[1]["turn"], 1)
        self.assertFalse(rows[1]["start"])
        self.assertEqual(rows[2]["turn"], 1)
        self.assertFalse(rows[2]["start"])
        self.assertEqual(project_session("d", "droid", recs)["turns"], 1)

    def test_tools_index_merges_catalog(self):
        # system.upserted 的 tools_catalog 按名字合并成 toolsIndex，后写覆盖前写，
        # 前端按工具名查 Schema（dsh 的 Schema 页签同款取数）。
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","turn":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"sys1","agent_id":"pi","session_id":"s","ts":2,"type":"system.upserted","turn":None,"payload":{
                "prompt_text":"p1","previous_prompt":None,
                "tools_catalog":[{"name":"Read","description":"read files","parameters":{}}]}}),
            rec(3, {"v":1,"id":"sys2","agent_id":"pi","session_id":"s","ts":3,"type":"system.upserted","turn":None,"payload":{
                "prompt_text":"p2","previous_prompt":"p1",
                "tools_catalog":[
                    {"name":"Write","description":"write files","parameters":{}},
                    {"name":"Read","description":"read files v2","parameters":{}},
                ]}}),
        ]
        page = project_session("s", "pi", recs)
        self.assertEqual(page["tools_index"]["Read"]["description"], "read files v2")
        self.assertEqual(page["tools_index"]["Write"]["description"], "write files")

    def test_droid_missing(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","turn":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"a","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed","request_no":1,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":"x"}}),
        ]
        row = project_session("d", "droid", recs)["rows"][0]
        self.assertEqual(row["usage"]["status"], "missing")
        self.assertIsNone(row["usage"]["input"])

    def test_compaction_and_failed_status(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"claude","session_id":"s","ts":1,"type":"session.opened","turn":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"u","agent_id":"claude","session_id":"s","ts":2,"type":"message.upserted","turn":1,"payload":{
                "message_id":"u1","role":"user","text":"hi","status":"completed","request_no":None,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
            rec(3, {"v":1,"id":"a","agent_id":"claude","session_id":"s","ts":3,"type":"message.upserted","turn":1,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":None,"started_at":3,"duration_ms":1,"output_text":"ok","model":"claude-opus-4"}}),
            rec(4, {"v":1,"id":"c","agent_id":"claude","session_id":"s","ts":4,"type":"compaction.boundary","turn":1,"payload":{
                "summary":"Context compacted","trigger":"auto","pre_tokens":8000,"post_tokens":1200}}),
            rec(5, {"v":1,"id":"te","agent_id":"claude","session_id":"s","ts":5,"type":"turn.ended","turn":1,"payload":{
                "usage":None,"status":"cancelled"}}),
        ]
        sess = project_session("s", "claude", recs)
        kinds = [r["kind"] for r in sess["rows"]]
        self.assertEqual(kinds, ["user", "assistant", "compacted"])
        self.assertEqual(sess["rows"][1]["model"], "claude-opus-4")
        self.assertEqual(sess["rows"][1]["status"], "cancelled")
        self.assertEqual(sess["rows"][2]["tag"], "COMPACTED")
        self.assertIn("8000 → 1200", sess["rows"][2]["note"])
        self.assertFalse(sess["rows"][2]["start"])

    def test_tail_sets_has_older(self):
        recs = [
            rec(i, {
                "v": 1, "id": f"m{i}", "agent_id": "pi", "session_id": "s",
                "ts": i, "type": "message.upserted", "turn": 1,
                "payload": {
                    "message_id": f"m{i}", "role": "user" if i % 2 else "assistant",
                    "text": f"row {i}", "status": "completed",
                    "request_no": None if i % 2 else i, "usage": None,
                    "started_at": i, "duration_ms": 1, "output_text": f"row {i}",
                },
            })
            for i in range(1, 6)
        ]
        page = project_session("s", "pi", recs, tail=2)
        self.assertTrue(page["has_older"])
        self.assertEqual([r["id"] for r in page["rows"]], ["m4", "m5"])


if __name__ == "__main__":
    unittest.main()
