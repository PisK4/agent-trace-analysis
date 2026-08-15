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
        self.assertEqual(sess["rows"][2]["parentId"], "a1")
        self.assertEqual(sess["rows"][2]["usage"]["status"], "n/a")

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
