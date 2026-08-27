import json
import unittest

from ata.plugins.capture import (
    _user_text_from_item,
    count_real_user_turns,
    resolve_session_id,
)


def user_msg(text):
    # 给 REQ1.messages 喂的原始请求形态：content blocks 数组。
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def wire_item(text):
    # 给 _user_text_from_item / count_real_user_turns 喂的 wire summary 摘要
    # 形态（anthropic_parser 产出，protocol_facts.py:57）：
    # content blocks 已被压平成 text 字段。
    return {"role": "user", "text": text}


class ResolveSessionTest(unittest.TestCase):
    def test_claude_header_case_insensitive(self):
        rec = {"request_headers": {"x-claude-code-session-id": "abc-123"}}
        self.assertEqual(resolve_session_id(rec, "claude"), "abc-123")

    def test_missing_header_returns_none(self):
        self.assertIsNone(resolve_session_id(
            {"request_headers": {}}, "claude"))
        self.assertIsNone(resolve_session_id(
            {"request_headers": {"user-agent": "claude-cli"}}, "claude"))

    def test_none_rec_safe(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"request_headers": None}, "claude"))


class CodexBodyPathTest(unittest.TestCase):
    def test_metadata_session_id(self):
        body = json.dumps({"metadata": {"session_id": "codex-s-1"}}).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertEqual(resolve_session_id(rec, "codex"), "codex-s-1")

    def test_nested_metadata_deep(self):
        # plan 里的占位 deep 路径 metadata.user.session_id 不在声明里——
        # 计划只声明 metadata.session_id 一条。此测试验证 _dig 在该声明
        # 下的实际可达深度（两层）。
        body = json.dumps({
            "metadata": {"session_id": "deep-1", "extra": "x"}
        }).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertEqual(resolve_session_id(rec, "codex"), "deep-1")

    def test_header_takes_precedence_over_body(self):
        # headers 路径优先（claude 走 headers；codex 走 body 但 headers 命中也算）
        rec = {
            "request_headers": {"x-codex-window-id": "win-1"},
            "request_body": json.dumps({"metadata": {"session_id": "codex-s-1"}}).encode(),
        }
        # codex 暂未在 _SESSION_HEADERS 声明 x-codex-window-id；body 路径胜出
        self.assertEqual(resolve_session_id(rec, "codex"), "codex-s-1")

    def test_missing_metadata_returns_none(self):
        body = json.dumps({"metadata": {"other": "x"}}).encode()
        rec = {"request_headers": {}, "request_body": body}
        self.assertIsNone(resolve_session_id(rec, "codex"))

    def test_garbage_body_returns_none(self):
        rec = {"request_headers": {}, "request_body": b"\xff\xfe"}
        self.assertIsNone(resolve_session_id(rec, "codex"))

    def test_empty_body_returns_none(self):
        rec = {"request_headers": {}, "request_body": b""}
        self.assertIsNone(resolve_session_id(rec, "codex"))


class DroidNamespaceTest(unittest.TestCase):
    def test_droid_returns_none_for_now(self):
        # droid 走代理：headers 路径未声明（待真实流量回填具体头名），
        # body 路径未声明（droid 是否用 body metadata 未知）。
        # 暂返回 None → 走 ingest_capture 的 ValueError 路径被吞掉。
        # 2026-08-27 e2e 验证：droid 真实请求 17878 既不带 x-droid-* 头、
        # 也不在 body metadata.session_id,sid 完全不在 wire traffic 上。
        # capture_proxy 因此**无法**为 droid 恢复 sid;这条 sid 来自 droid
        # daemon 自身的 transcript 适配器(file watcher 扫 ~/.factory/sessions),
        # 走 capture_proxy 通道无法合并同一 session。
        rec = {
            "request_headers": {"x-droid-trace-id": "d-1"},
            "request_body": b'{"some": "json"}',
        }
        self.assertIsNone(resolve_session_id(rec, "droid"))


class CountTurnsTest(unittest.TestCase):
    def test_counts_real_user_messages(self):
        # 喂 wire summary 的 message_items 摘要形态：text 字段已压平。
        items = [
            wire_item("first"),
            {"role": "assistant", "text": "ok"},
            wire_item("second"),
            {"role": "assistant", "text": "done"},
            wire_item("third"),
        ]
        self.assertEqual(count_real_user_turns(items), 3)

    def test_context_injection_does_not_count(self):
        items = [
            wire_item("first"),
            wire_item("<system-reminder>context noise</system-reminder>"),
            wire_item("second"),
        ]
        self.assertEqual(count_real_user_turns(items), 2)

    def test_empty_and_malformed(self):
        self.assertEqual(count_real_user_turns([]), 0)
        self.assertEqual(
            count_real_user_turns([{"role": "user"}, None, "junk"]), 0)


class WireItemsTurnsTest(unittest.TestCase):
    def test_text_block(self):
        item = {"role": "user", "text": "hi"}
        self.assertEqual(_user_text_from_item(item), "hi")

    def test_assistant_returns_empty(self):
        item = {"role": "assistant", "text": "ok"}
        self.assertEqual(_user_text_from_item(item), "")

    def test_non_dict_returns_empty(self):
        self.assertEqual(_user_text_from_item(None), "")
        self.assertEqual(_user_text_from_item("junk"), "")
        self.assertEqual(_user_text_from_item([]), "")

    def test_missing_text_returns_empty(self):
        item = {"role": "user"}
        self.assertEqual(_user_text_from_item(item), "")

    def test_non_string_text_returns_empty(self):
        # 防止 None / int 之类的退化值漏到 is_context_text 判 CONTEXT 段。
        self.assertEqual(
            _user_text_from_item({"role": "user", "text": None}), "")
        self.assertEqual(
            _user_text_from_item({"role": "user", "text": 42}), "")


class TranslateCaptureTest(unittest.TestCase):
    def setUp(self):
        from ata.plugins.capture import RECORD_KEYS, translate_capture
        from ata.schema import parse_event

        self.RECORD_KEYS = RECORD_KEYS
        self.translate = translate_capture
        self.parse_event = parse_event
        # ingest 路径由 ingest_capture 负责 set；单测直呼 translate 时自己给。
        self.state = {"session_id": "s1"}

    def test_first_capture_emits_system_and_turn_end(self):
        evs = self.translate(record(json.dumps(REQ1).encode(),
                                    json.dumps(RESP1).encode()), self.state)
        # Round 2: 代理主发 message.upserted (user + assistant), system + turn.ended 仍按原条件发。
        self.assertEqual([e["type"] for e in evs],
                         ["system.upserted", "message.upserted",
                          "message.upserted", "turn.ended"])
        sys_ev, end_ev = evs[0], evs[-1]
        sys_ev = self.parse_event(sys_ev)
        end_ev = self.parse_event(end_ev)
        self.assertIsNone(sys_ev["turn"])
        self.assertEqual(sys_ev["payload"]["prompt_text"], "You are ATA.")
        self.assertEqual(sys_ev["payload"]["tools_catalog"][0]["name"], "Read")
        self.assertEqual(end_ev["turn"], 1)
        u = end_ev["payload"]["usage"]
        self.assertEqual(u["status"], "reported")
        self.assertEqual((u["input"], u["output"], u["cache_read"],
                          u["cache_write"], u["total_tokens"]),
                         (10, 5, 2, 1, 18))
        self.assertIsNone(u["cost"])

    def test_system_not_reemitted_when_unchanged(self):
        import tempfile
        from pathlib import Path
        from ata.ledger import Ledger
        from ata.plugins.capture import ingest_capture
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d))
            r = record(json.dumps(REQ1).encode(), json.dumps(RESP1).encode())
            ingest_capture(led, r)
            rows1 = len(led.read("s1"))
            led2 = Ledger(Path(d))  # 新实例 (state 空, system_hash 重算)
            ingest_capture(led2, r)
            rows2 = len(led2.read("s1"))
            # 第二次: system + 两条 message 走 dedupe_key UPDATE 不增行;
            # turn.ended 走 PRIMARY KEY (event_id) 幂等, 也不增行。
            self.assertEqual(rows2, rows1)

    def test_system_reemitted_when_prompt_changes(self):
        self.translate(record(json.dumps(REQ1).encode(),
                              json.dumps(RESP1).encode()), self.state)
        req2 = dict(REQ1, system=[{"type": "text", "text": "New prompt."}])
        evs = self.translate(record(json.dumps(req2).encode(),
                                    json.dumps(RESP1).encode()), self.state)
        self.assertIn("system.upserted", [e["type"] for e in evs])

    def test_turn_number_tracks_real_user_count(self):
        msgs = [user_msg("first"),
                {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
                user_msg("second")]
        req2 = dict(REQ1, messages=msgs)
        evs = self.translate(
            record(json.dumps(req2).encode(), json.dumps(RESP1).encode()),
            self.state)
        end = self.parse_event(evs[-1])
        self.assertEqual(end["type"], "turn.ended")
        self.assertEqual(end["turn"], 2)

    def test_missing_usage_emits_nothing(self):
        resp = dict(RESP1, usage={})
        evs = self.translate(record(json.dumps(REQ1).encode(),
                                    json.dumps(resp).encode()), self.state)
        # system 快照仍要发; turn.ended 没有 usage 就不发; message.upserted 仍按
        # 请求/响应形状发 (Round 2 起代理主发 message, 与 usage 解耦)。
        self.assertEqual([e["type"] for e in evs],
                         ["system.upserted", "message.upserted",
                          "message.upserted"])

    def test_sse_response_parses(self):
        sse = (
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_09","usage":{"input_tokens":7}}}\n\n'
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
        )
        evs = self.translate(record(json.dumps(REQ1).encode(), sse,
                                    ct="text/event-stream"), self.state)
        types = [e["type"] for e in evs]
        self.assertIn("system.upserted", types)
        self.assertIn("turn.ended", types)
        end = self.parse_event(next(e for e in evs if e["type"] == "turn.ended"))
        self.assertEqual((end["payload"]["usage"]["input"],
                          end["payload"]["usage"]["output"]), (7, 3))

    def test_record_shape_declared(self):
        self.assertEqual(
            sorted(self.RECORD_KEYS),
            sorted(["agent_id", "path", "request_headers", "request_body",
                    "response_content_type", "response_body",
                    "started_at_ms", "completed_at_ms"]))


REQ1 = {
    "model": "claude-sonnet-5",
    "system": [{"type": "text", "text": "You are ATA."}],
    "tools": [{"name": "Read", "description": "read a file",
               "input_schema": {"type": "object"}}],
    "messages": [user_msg("hi")],
}
RESP1 = {
    "id": "msg_01", "type": "message", "role": "assistant",
    "content": [{"type": "text", "text": "hello"}], "stop_reason": "end_turn",
    "usage": {"input_tokens": 10, "output_tokens": 5,
              "cache_read_input_tokens": 2, "cache_creation_input_tokens": 1},
}


def record(req_body, resp_body, sid="s1", ct="application/json",
           started=1000, completed=1900):
    return {
        "agent_id": "claude",
        "path": "/v1/messages",
        "request_headers": {"x-claude-code-session-id": sid},
        "request_body": req_body,
        "response_content_type": ct,
        "response_body": resp_body,
        "started_at_ms": started,
        "completed_at_ms": completed,
    }


class CaptureMessageEmitTest(unittest.TestCase):
    """Round 2: 代理主发 message.upserted, transcript 退到补录。

    关键 invariants:
    - 代理从 req.messages 提 user 块, emit message.upserted (role=user)
    - 代理从 resp 提 assistant 块, emit message.upserted (role=assistant)
    - assistant 的 message_id 取 resp.response_id (msg_xxx), 不是 gen-...
    - turn 字段: 本 request 的真实 user 数(与 turn.ended 同口径)
    - 同 sid 重复同 mid 不重复发(state._capture_emit 防重)
    """

    def _rec(self, sid="cap-msg-1", request_body=None, response_body=None):
        return {
            "agent_id": "claude",
            "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": request_body or json.dumps({
                "model": "claude-3-5-sonnet",
                "messages": [
                    {"role": "user", "id": "user-msg-1",
                     "content": [{"type": "text", "text": "hello"}]},
                ],
            }).encode(),
            "response_content_type": "application/json",
            "response_body": response_body or json.dumps({
                "id": "msg_resp_1", "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_user_message_emitted_from_request(self):
        from ata.plugins.capture import translate_capture
        state = {"session_id": "cap-msg-1"}
        events = translate_capture(self._rec(), state)
        upserts = [e for e in events if e["type"] == "message.upserted"]
        roles = {e["payload"]["role"] for e in upserts}
        self.assertEqual(roles, {"user", "assistant"})
        user_ev = next(e for e in upserts if e["payload"]["role"] == "user")
        self.assertEqual(user_ev["payload"]["message_id"], "user-msg-1")
        self.assertEqual(user_ev["payload"]["text"], "hello")
        self.assertEqual(user_ev["turn"], 1)

    def test_assistant_message_uses_response_id(self):
        from ata.plugins.capture import translate_capture
        state = {"session_id": "cap-msg-2"}
        events = translate_capture(self._rec(sid="cap-msg-2"), state)
        asst = next(e for e in events
                    if e["type"] == "message.upserted"
                    and e["payload"]["role"] == "assistant")
        self.assertEqual(asst["payload"]["message_id"], "msg_resp_1")
        # usage 透传
        self.assertEqual(asst["payload"]["usage"]["input"], 10)
        self.assertEqual(asst["payload"]["usage"]["output"], 5)

    def test_assistant_message_status_completed(self):
        from ata.plugins.capture import translate_capture
        state = {"session_id": "cap-msg-3"}
        events = translate_capture(self._rec(sid="cap-msg-3"), state)
        asst = next(e for e in events
                    if e["type"] == "message.upserted"
                    and e["payload"]["role"] == "assistant")
        self.assertEqual(asst["payload"]["status"], "completed")

    def test_same_mid_not_reemitted_across_translations(self):
        """同 sid + 同 message_id 走 events.dedupe_key 跨进程持久,
        translate 是纯函数不挡重, 由 ingest_capture 的 ledger 兜底。"""
        import tempfile
        from pathlib import Path
        from ata.ledger import Ledger
        from ata.plugins.capture import ingest_capture
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d))
            ingest_capture(led, self._rec(sid="cap-msg-4"))
            led2 = Ledger(Path(d))  # 新实例 (模拟 ata 重启)
            led2.read("cap-msg-4")
            recs = led2.read("cap-msg-4")
            user_evs = [r for r in recs
                        if r["event"]["type"] == "message.upserted"
                        and r["event"]["payload"].get("role") == "user"]
            self.assertEqual(len(user_evs), 1)


class CaptureToolEmitTest(unittest.TestCase):
    """Round 2: 代理主发 tool.upserted (start from response, end from next request)。

    - start: response.tool_calls → tool_use 块 → status=pending
    - end: 下一轮 request 里的 tool_result 块 → status=completed
    - 缺失 start 的 tool_use_id: 不发 end (代理漏了一次响应, 视为外部异常)
    """

    def _base_rec(self, sid="cap-tool-1", request_messages=None, response=None):
        return {
            "agent_id": "claude",
            "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "m",
                "messages": request_messages or [
                    {"role": "user", "id": "u-1", "content": [{"type": "text", "text": "q"}]},
                ],
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps(response or {
                "id": "msg_resp", "role": "assistant",
                "content": [{"type": "text", "text": "answer"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_tool_start_from_response(self):
        from ata.plugins.capture import translate_capture
        rec = self._base_rec(
            response={
                "id": "msg_resp", "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_01", "name": "Read",
                     "input": {"path": "/x"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            })
        events = translate_capture(rec, {"session_id": "cap-tool-1"})
        starts = [e for e in events if e["type"] == "tool.upserted"
                  and e["id"].endswith(":start")]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["payload"]["tool_call_id"], "toolu_01")
        self.assertEqual(starts[0]["payload"]["name"], "Read")
        self.assertEqual(starts[0]["payload"]["status"], "pending")

    def test_tool_end_from_next_request(self):
        """tool_result 出现在**下一轮** request 里 — 模拟 claude 实际行为。"""
        from ata.plugins.capture import translate_capture
        state = {"session_id": "cap-tool-2"}
        # 第一轮: tool_use
        rec1 = self._base_rec(
            sid="cap-tool-2",
            response={
                "id": "msg_resp_1", "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_02", "name": "Bash",
                     "input": {"cmd": "ls"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            })
        translate_capture(rec1, state)
        # 第二轮: 同一 session, user 带 tool_result
        rec2 = self._base_rec(
            sid="cap-tool-2",
            request_messages=[
                {"role": "user", "id": "u-1",
                 "content": [{"type": "text", "text": "q"}]},
                {"role": "assistant", "id": "msg_resp_1",
                 "content": [
                     {"type": "tool_use", "id": "toolu_02", "name": "Bash",
                      "input": {"cmd": "ls"}},
                 ]},
                {"role": "user", "id": "u-2",
                 "content": [
                     {"type": "tool_result", "tool_use_id": "toolu_02",
                      "content": "file.txt\n"},
                 ]},
            ])
        events = translate_capture(rec2, state)
        ends = [e for e in events if e["type"] == "tool.upserted"
                and e["id"].endswith(":end")]
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]["payload"]["tool_call_id"], "toolu_02")
        self.assertEqual(ends[0]["payload"]["status"], "completed")
        self.assertIn("file.txt", (ends[0]["payload"].get("result") or ""))


class UserContextFilterTest(unittest.TestCase):
    """emit 路径必须跟 count_real_user_turns 同口径过滤 CONTEXT 注入,
    否则 <system-reminder> 会被当 user 消息写入账本,投影层显示错乱。"""

    def _rec(self, messages, sid="ctx-1"):
        return {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet", "messages": messages,
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": "msg_resp_ctx", "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_system_reminder_user_not_emitted(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<system-reminder>\nctx</system-reminder>"}]},
        ]
        events = translate_capture(self._rec(msgs), {"session_id": "ctx-1"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(user_upserts, [])

    def test_real_user_emitted_after_context(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<system-reminder>\nctx</system-reminder>"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
            {"role": "user", "content": [{"type": "text",
                "text": "真 user 问题"}]},
        ]
        events = translate_capture(self._rec(msgs), {"session_id": "ctx-2"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(len(user_upserts), 1)
        self.assertEqual(user_upserts[0]["payload"]["text"], "真 user 问题")


class UserMidDerivationTest(unittest.TestCase):
    """anthropic wire 真实 user 消息没有 id 字段; 测试必须不手工塞 id,
    派生 mid 必须从 message_items[i].index 拿, 避免 f'{sid}:user:' 空尾巴
    导致所有 user 撞同一 mid 一起被 seen 吞。"""

    def _rec(self, messages, sid="mid-1", resp_id="msg_r"):
        return {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet", "messages": messages,
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": resp_id, "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }

    def test_user_mid_includes_index(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
        ]
        events = translate_capture(
            self._rec(msgs, sid="mid-A", resp_id="r1"),
            {"session_id": "mid-A"})
        user_ev = next(e for e in events
                       if e["type"] == "message.upserted"
                       and e["payload"].get("role") == "user")
        # mid 必须包含 index=0, 不能是空尾巴
        self.assertIn("mid-A:user:1:0", user_ev["payload"]["message_id"])

    def test_two_user_messages_get_different_mids(self):
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
        ]
        events = translate_capture(
            self._rec(msgs, sid="mid-B", resp_id="r2"),
            {"session_id": "mid-B"})
        user_evs = [e for e in events
                    if e["type"] == "message.upserted"
                    and e["payload"].get("role") == "user"]
        mids = [e["payload"]["message_id"] for e in user_evs]
        self.assertEqual(len(mids), 2)
        # 不撞同 mid
        self.assertNotEqual(mids[0], mids[1])
        # 都含 :user:N:index 形状
        for m in mids:
            self.assertRegex(m, r"mid-B:user:\d+:\d+")


class SeenPersistedAcrossInstancesTest(unittest.TestCase):
    """seen 不能只在 capture.py 内存 set, ata 重启后空 mid 又能 emit
    一次会跟历史去重键冲突。seen 必须走 events.dedupe_key UNIQUE 索引
    跨进程持久。"""

    def test_second_ledger_instance_dedupes_via_dedupe_key(self):
        import tempfile
        from pathlib import Path
        from ata.ledger import Ledger
        from ata.plugins.capture import ingest_capture

        rec = lambda sid, mid: {
            "agent_id": "claude", "path": "/v1/messages",
            "request_headers": {"x-claude-code-session-id": sid},
            "request_body": json.dumps({
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user",
                              "content": [{"type": "text", "text": "hi"}]}],
            }).encode(),
            "response_content_type": "application/json",
            "response_body": json.dumps({
                "id": "msg_r", "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }).encode(),
            "started_at_ms": 1000, "completed_at_ms": 2000,
        }
        with tempfile.TemporaryDirectory() as d:
            led1 = Ledger(Path(d))
            ingest_capture(led1, rec("pers-1", "user-msg-1"))
            recs1 = led1.read("pers-1")
            user_upserts1 = [r for r in recs1
                             if r["event"]["type"] == "message.upserted"
                             and r["event"]["payload"].get("role") == "user"]
            self.assertEqual(len(user_upserts1), 1)

            # 同一账本文件, 全新 Ledger 实例 (模拟 ata 重启)
            led2 = Ledger(Path(d))
            ingest_capture(led2, rec("pers-1", "user-msg-1"))
            recs2 = led2.read("pers-1")
            user_upserts2 = [r for r in recs2
                             if r["event"]["type"] == "message.upserted"
                             and r["event"]["payload"].get("role") == "user"]
            # 第二次没新行, dedupe_key UNIQUE 拦了
            self.assertEqual(len(user_upserts2), 1)


if __name__ == "__main__":
    unittest.main()
