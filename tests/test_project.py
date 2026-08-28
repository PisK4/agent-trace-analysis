import unittest
from ata.project import project_session
from ata.schema import parse_event


def rec(seq, ev):
    return {"seq": seq, "event": parse_event(ev)}


class ProjectTest(unittest.TestCase):
    def test_usage_and_order(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"ts","agent_id":"pi","session_id":"s","ts":2,"type":"turn.started","observed_turn_ordinal":1,"payload":{}}),
            rec(3, {"v":1,"id":"u","agent_id":"pi","session_id":"s","ts":3,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"u1","role":"user","text":"hello","status":"completed","request_no":None,
                "usage":None,"started_at":3,"duration_ms":10,"output_text":None}}),
            rec(4, {"v":1,"id":"a","agent_id":"pi","session_id":"s","ts":4,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":{"status":"reported","input":10,"output":2,"cache_read":1,"cache_write":0,"total_tokens":13,"cost":None},
                "started_at":4,"duration_ms":20,"output_text":"ok"}}),
            rec(5, {"v":1,"id":"t","agent_id":"pi","session_id":"s","ts":5,"type":"tool.upserted","observed_turn_ordinal":1,"payload":{
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
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"u","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"u1","role":"user","text":"<system-reminder>The tools listed below are available",
                "status":"completed","request_no":None,"usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
        ]
        row = project_session("d", "droid", recs)["rows"][0]
        self.assertEqual(row["kind"], "context")
        self.assertEqual(row["tag"], "CONTEXT")
        self.assertFalse(row["start"])

    def test_context_does_not_open_turn(self):
        """Round 2 收窄后: 代理主发 turn, 投影层不再 remap context.turn。

        老逻辑: project.py L213-224 把 context 行的 turn 拉回前一条 user 的
        turn, 防止"第 2 轮"挂在 reminder 上。代理主发后, context 的 turn 由
        上游写入的 turn 决定 (可能与 user 同 turn, 也可能独立), 投影层不再
        干预 — 所以本测试 context 的 turn 保留原值 2 (老测试期望被改回 1)。
        """
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"u","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"u1","role":"user","text":"hello","status":"completed","request_no":None,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
            rec(3, {"v":1,"id":"c","agent_id":"droid","session_id":"d","ts":3,"type":"message.upserted","observed_turn_ordinal":2,"payload":{
                "message_id":"c1","role":"user","text":"<system-reminder>The tools listed below are available",
                "status":"completed","request_no":None,"usage":None,"started_at":3,"duration_ms":1,"output_text":None}}),
            rec(4, {"v":1,"id":"a","agent_id":"droid","session_id":"d","ts":4,"type":"message.upserted","observed_turn_ordinal":2,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":None,"started_at":4,"duration_ms":1,"output_text":"ok"}}),
        ]
        rows = project_session("d", "droid", recs)["rows"]
        self.assertEqual([r["kind"] for r in rows], ["user", "context", "assistant"])
        self.assertEqual(rows[0]["turn"], 1)
        self.assertTrue(rows[0]["start"])
        # Round 2: context.turn 保留原值 2 (代理端决定), 不再 remap 到 1
        self.assertEqual(rows[1]["turn"], 2)
        self.assertFalse(rows[1]["start"])
        # 新行为: assistant.turn=2 是新轮起点, start=True (老 remap 把 a1
        # 也压回 turn=1 时代 assistant.start=False)
        self.assertEqual(rows[2]["turn"], 2)
        self.assertTrue(rows[2]["start"])

    def test_orphan_assistant_not_remapped_to_one(self):
        """Round 2: 代理主发 turn, 投影不再把"无前导 user 的 assistant 行"
        remap 回 turn=1 (老 last_user_turn remap 的副作用)。"""
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"s"}}),
            rec(2, {"v":1,"id":"u","agent_id":"pi","session_id":"s","ts":2,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"u1","role":"user","text":"hi","status":"completed","request_no":None,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
            rec(3, {"v":1,"id":"a1","agent_id":"pi","session_id":"s","ts":3,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"a1","role":"assistant","text":"a1","status":"completed","request_no":1,
                "usage":None,"started_at":3,"duration_ms":1,"output_text":"a1"}}),
            rec(4, {"v":1,"id":"a2","agent_id":"pi","session_id":"s","ts":4,"type":"message.upserted","observed_turn_ordinal":2,"payload":{
                "message_id":"a2","role":"assistant","text":"a2","status":"completed","request_no":2,
                "usage":None,"started_at":4,"duration_ms":1,"output_text":"a2"}}),
        ]
        rows = project_session("s", "pi", recs)["rows"]
        # a2 保留 turn=2 (没有前导 user, 投影不再 remap 到 1)
        a2 = next(r for r in rows if r.get("text") == "a2")
        self.assertEqual(a2["turn"], 2)

    def test_tools_index_merges_catalog(self):
        # system.upserted 的 tools_catalog 按名字合并成 toolsIndex，后写覆盖前写，
        # 前端按工具名查 Schema（dsh 的 Schema 页签同款取数）。
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"sys1","agent_id":"pi","session_id":"s","ts":2,"type":"system.upserted","observed_turn_ordinal":None,"payload":{
                "prompt_text":"p1","previous_prompt":None,
                "tools_catalog":[{"name":"Read","description":"read files","parameters":{}}]}}),
            rec(3, {"v":1,"id":"sys2","agent_id":"pi","session_id":"s","ts":3,"type":"system.upserted","observed_turn_ordinal":None,"payload":{
                "prompt_text":"p2","previous_prompt":"p1",
                "tools_catalog":[
                    {"name":"Write","description":"write files","parameters":{}},
                    {"name":"Read","description":"read files v2","parameters":{}},
                ]}}),
        ]
        page = project_session("s", "pi", recs)
        self.assertEqual(page["tools_index"]["Read"]["description"], "read files v2")
        self.assertEqual(page["tools_index"]["Write"]["description"], "write files")

    def test_system_catalog_forward_fill(self):
        # 目录去重落库后，缺省轮次沿用最近一份目录（前向填充）。
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"pi","session_id":"s","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"sys1","agent_id":"pi","session_id":"s","ts":2,"type":"system.upserted","observed_turn_ordinal":None,"payload":{
                "prompt_text":"p1","previous_prompt":None,
                "tools_catalog":[{"name":"Read","description":"read files","parameters":{}}],
                "skills_catalog":[{"name":"s1","description":"d"}]}}),
            rec(3, {"v":1,"id":"sys2","agent_id":"pi","session_id":"s","ts":3,"type":"system.upserted","observed_turn_ordinal":None,"payload":{
                "prompt_text":"p2","previous_prompt":"p1"}}),
        ]
        page = project_session("s", "pi", recs)
        rows = [row for row in page["rows"] if row["kind"] == "system"]
        self.assertEqual(rows[0]["skillsCatalog"][0]["name"], "s1")
        self.assertEqual(rows[1]["toolsCatalog"][0]["name"], "Read")
        self.assertEqual(rows[1]["skillsCatalog"], rows[0]["skillsCatalog"])

    def test_droid_missing(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"droid","session_id":"d","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"d"}}),
            rec(2, {"v":1,"id":"a","agent_id":"droid","session_id":"d","ts":2,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"a1","role":"assistant","text":"x","status":"completed","request_no":1,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":"x"}}),
        ]
        row = project_session("d", "droid", recs)["rows"][0]
        self.assertEqual(row["usage"]["status"], "missing")
        self.assertIsNone(row["usage"]["input"])

    def test_compaction_and_failed_status(self):
        recs = [
            rec(1, {"v":1,"id":"o","agent_id":"claude","session_id":"s","ts":1,"type":"session.opened","observed_turn_ordinal":None,"payload":{"title":"t"}}),
            rec(2, {"v":1,"id":"u","agent_id":"claude","session_id":"s","ts":2,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"u1","role":"user","text":"hi","status":"completed","request_no":None,
                "usage":None,"started_at":2,"duration_ms":1,"output_text":None}}),
            rec(3, {"v":1,"id":"a","agent_id":"claude","session_id":"s","ts":3,"type":"message.upserted","observed_turn_ordinal":1,"payload":{
                "message_id":"a1","role":"assistant","text":"ok","status":"completed","request_no":1,
                "usage":None,"started_at":3,"duration_ms":1,"output_text":"ok","model":"claude-opus-4"}}),
            rec(4, {"v":1,"id":"c","agent_id":"claude","session_id":"s","ts":4,"type":"compaction.boundary","observed_turn_ordinal":None,"payload":{
                "summary":"Context compacted","trigger":"auto","pre_tokens":8000,"post_tokens":1200}}),
            rec(5, {"v":1,"id":"te","agent_id":"claude","session_id":"s","ts":5,"type":"turn.ended","observed_turn_ordinal":1,"payload":{
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
                "ts": i, "type": "message.upserted", "observed_turn_ordinal": 1,
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


class TitleAuthorityParityTest(unittest.TestCase):
    """投影层的标题折叠与账本侧 fold_session_meta 必须产出同一标题。

    架构评审候选 4：「用户改名后 opened 不再覆盖」曾同时实现在账本索引与
    投影重推两处。此测试让两份实现互为对照；漂移即红。
    """

    def _events(self):
        return [
            {"seq": 1, "event": {"v": 1, "id": "o", "agent_id": "pi", "session_id": "s",
                                 "ts": 1000, "type": "session.opened", "observed_turn_ordinal": None,
                                 "payload": {"title": "auto-title"}}},
            {"seq": 2, "event": {"v": 1, "id": "r", "agent_id": "pi", "session_id": "s",
                                 "ts": 2000, "type": "session.renamed", "observed_turn_ordinal": None,
                                 "payload": {"title": "user-name"}}},
            {"seq": 3, "event": {"v": 1, "id": "o2", "agent_id": "pi", "session_id": "s",
                                 "ts": 3000, "type": "session.opened", "observed_turn_ordinal": None,
                                 "payload": {"title": "late-opened"}}},
        ]

    def test_projection_and_fold_agree(self):
        from ata.fold import fold_session_meta
        recs = self._events()
        page = project_session("s", "pi", recs)
        folded = None
        for rec in recs:
            folded = fold_session_meta(folded, rec["event"])
        self.assertEqual(page["title"], folded["title"])

    def test_renamed_beats_late_opened(self):
        page = project_session("s", "pi", self._events())
        self.assertEqual(page["title"], "user-name")


if __name__ == "__main__":
    unittest.main()
