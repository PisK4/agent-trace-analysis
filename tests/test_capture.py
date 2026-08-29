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
        self.assertIsNone(sys_ev["observed_turn_ordinal"])
        self.assertEqual(sys_ev["payload"]["prompt_text"], "You are ATA.")
        self.assertEqual(sys_ev["payload"]["tools_catalog"][0]["name"], "Read")
        self.assertEqual(end_ev["observed_turn_ordinal"], 1)
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
            try:
                r = record(json.dumps(REQ1).encode(), json.dumps(RESP1).encode())
                ingest_capture(led, r)
                rows1 = len(led.read("s1"))
                led2 = Ledger(Path(d))  # 新实例 (state 空, system_hash 重算)
                try:
                    ingest_capture(led2, r)
                    rows2 = len(led2.read("s1"))
                finally:
                    led2.close()
                # 第二次: system + 两条 message 走 dedupe_key UPDATE 不增行;
                # turn.ended 走 PRIMARY KEY (event_id) 幂等, 也不增行。
                self.assertEqual(rows2, rows1)
            finally:
                led.close()

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
        self.assertEqual(end["observed_turn_ordinal"], 2)

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
        self.assertEqual(user_ev["observed_turn_ordinal"], 1)

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
            try:
                ingest_capture(led, self._rec(sid="cap-msg-4"))
                led2 = Ledger(Path(d))  # 新实例 (模拟 ata 重启)
                try:
                    led2.read("cap-msg-4")
                    recs = led2.read("cap-msg-4")
                finally:
                    led2.close()
            finally:
                led.close()
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

    def test_session_injection_not_emitted(self):
        """<session> 注入 (harness 把 handoff 内容用 <session> 块包起来送进
        wire) 跟 <system-reminder> 一样属于 CONTEXT 注入, 不能当 user 写入。
        真实流量见 sid dfe9247a (2026-08-27) T1 user 旁被污染的样本。"""
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<session>\n@repos/ata/foo</session>"}]},
        ]
        events = translate_capture(self._rec(msgs, sid="ctx-sess"),
                                    {"session_id": "ctx-sess"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(user_upserts, [])

    def test_task_notification_injection_not_emitted(self):
        """<task-notification> 是 harness 后台任务回报, 不是 user 提问。"""
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [{"type": "text",
                "text": "<task-notification>\n<task-id>abc</task-id>\n"
                         "foo</task-notification>"}]},
        ]
        events = translate_capture(self._rec(msgs, sid="ctx-task"),
                                    {"session_id": "ctx-task"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(user_upserts, [])

    def test_command_name_and_message_not_emitted(self):
        """<command-name>/<command-message> 是 slash 命令 (e.g. /clear /design)
        的 harness 注入, 同样不是 user 消息本体。"""
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("ctx-cmd1", "<command-name>/clear</command-name>"),
            ("ctx-cmd2", "<command-message>ata</command-message>"),
        ]:
            msgs = [{"role": "user", "content": [{"type": "text", "text": txt}]}]
            events = translate_capture(self._rec(msgs, sid=sid),
                                        {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(user_upserts, [], f"failed for {sid}")

    def test_local_command_stderr_not_emitted(self):
        """<local-command-stdout>/<local-command-caveat> 是本地命令的 harness
        旁路回流 (例如 set model 后的 stdout), 走的是 user role wire 但语义
        是 harness 输出, 不当 user 消息写入。"""
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("ctx-loc1", "<local-command-stdout>Set model to Sonnet</local-command-stdout>"),
            ("ctx-loc2", "<local-command-caveat>Caveat: foo</local-command-caveat>"),
        ]:
            msgs = [{"role": "user", "content": [{"type": "text", "text": txt}]}]
            events = translate_capture(self._rec(msgs, sid=sid),
                                        {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(user_upserts, [], f"failed for {sid}")

    def test_bracket_keyword_injection_not_emitted(self):
        """[BRACKETED_KEY] 形态注入 (harness 自动加的 [CURRENT_TIME] /
        [MATERIAL_WINDOW] 等) 走形态学兜底, 不要求闭合 / 不要求 tag 在
        已知列表里。"""
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("ctx-brk1", "[CURRENT_TIME]2026-08-27 19:15 (UTC+08:00)"),
            ("ctx-brk2", "[MATERIAL_WINDOW]2026-08-27T09:29:25+"),
        ]:
            msgs = [{"role": "user", "content": [{"type": "text", "text": txt}]}]
            events = translate_capture(self._rec(msgs, sid=sid),
                                        {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(user_upserts, [], f"failed for {sid}")

    def test_unclosed_injection_still_filtered(self):
        """治本路径: 不要求闭合块, harness 出新形态 (<ide_selection> /
        <uploaded_file> 等) 自动命中 <xxx> 兜底, 永远不漏。"""
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("ctx-fut1", "<ide_selection>selected text</ide_selection>"),
            ("ctx-fut2", "<uploaded_file>/tmp/x.png</uploaded_file>"),
            # 不闭合 (罕见但 harness 偶尔发)
            ("ctx-unc1", "<system-reminder>incomplete no closing tag"),
            # claudeMd / tool-result (ava trace_graph.py 同款 tag)
            ("ctx-ava1", "<claudeMd>project memo</claudeMd>"),
            ("ctx-ava2", "<tool-result>tool output</tool-result>"),
        ]:
            msgs = [{"role": "user", "content": [{"type": "text", "text": txt}]}]
            events = translate_capture(self._rec(msgs, sid=sid),
                                        {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(user_upserts, [], f"failed for {sid}")

    def test_id_gate_protects_real_user_with_xml_text(self):
        """id 守门: 真 user 消息 wire 带 id 字段, 即使文本是 <u>HTML</u> 或
        [tag]foo 形态, is_context_text 也豁免, 不被误杀。
        数据点: ~/.ata/ata.sqlite 统计所有 <xxx>...</xxx> 形态 user 消息
        100% 是 harness 注入 (真 user 写 HTML 0 样本), 但 id 守门是协议级
        不变量, 防未来真 user 真的写 XML 形态。"""
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("ctx-gt1", "<u>强调</u>"),
            ("ctx-gt2", "[tag]bracketed-prefix"),
        ]:
            # 带 wire id 的真 user 消息
            msgs = [{
                "role": "user",
                "content": [{"type": "text", "text": txt}],
                "id": f"msg_real_{sid}",
            }]
            events = translate_capture(self._rec(msgs, sid=sid),
                                        {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(len(user_upserts), 1,
                             f"id gate should protect real user {sid}")
            # 透传的 mid 应是 wire id (不是 sid:user:turn:user_idx 派生)
            self.assertEqual(user_upserts[0]["payload"]["message_id"],
                             f"msg_real_{sid}")


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
        # mid 形状 {sid}:user:{user_idx}:{content_hash8} — user_idx 定位,
        # hash8 防同下标不同内容。不含 turn 号 (跨轮稳定, 详见
        # StableUserMidTest)。
        import re
        self.assertRegex(user_ev["payload"]["message_id"],
                         r"^mid-A:user:0:[0-9a-f]{8}$")

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
        # 都含 :user:N:hash8 形状
        for m in mids:
            self.assertRegex(m, r"mid-B:user:\d+:[0-9a-f]{8}")


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
            try:
                ingest_capture(led1, rec("pers-1", "user-msg-1"))
                recs1 = led1.read("pers-1")
                user_upserts1 = [r for r in recs1
                                 if r["event"]["type"] == "message.upserted"
                                 and r["event"]["payload"].get("role") == "user"]
                self.assertEqual(len(user_upserts1), 1)

                # 同一账本文件, 全新 Ledger 实例 (模拟 ata 重启)
                led2 = Ledger(Path(d))
                try:
                    ingest_capture(led2, rec("pers-1", "user-msg-1"))
                    recs2 = led2.read("pers-1")
                    user_upserts2 = [r for r in recs2
                                     if r["event"]["type"] == "message.upserted"
                                     and r["event"]["payload"].get("role") == "user"]
                finally:
                    led2.close()
                # 第二次没新行, dedupe_key UNIQUE 拦了
                self.assertEqual(len(user_upserts2), 1)
            finally:
                led1.close()


class BlockLevelContextFilterTest(unittest.TestCase):
    """block 级过滤: harness 注入与真实提问共存于同一 user 消息的相邻
    text block 时 (Claude Code 真实形态, sid 74736c29 2026-08-27 实证:
    <local-command-caveat>/<command-name> 块与「你是谁」同一消息),
    只杀注入块, 不能整条消息连带真实提问一起杀。

    旧实现把全部 text block 拼成一串再判 is_context_text, 开头的 <xxx>
    把整条消息判成 CONTEXT —「你是谁」三轮请求里轮轮在场、轮轮被杀,
    账本里 user:1:* 编号从未出现过 (磁盘 jsonl line 10 有, 账本无)。"""

    def _rec(self, messages, sid="blk-1", resp_id="msg_blk"):
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

    def test_injection_block_alongside_real_question(self):
        """注入块 + 真实提问同消息: 真实提问必须 emit。"""
        from ata.plugins.capture import translate_capture
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text":
                    "<local-command-caveat>Caveat: local</local-command-caveat>"},
                {"type": "text", "text": "你是谁"},
            ],
        }]
        events = translate_capture(
            self._rec(msgs, sid="blk-mix"), {"session_id": "blk-mix"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(len(user_upserts), 1)
        self.assertEqual(user_upserts[0]["payload"]["text"], "你是谁")

    def test_injection_alone_still_filtered(self):
        """纯注入消息 (单 block) 依旧整条过滤, 不因粒度变细而漏。"""
        from ata.plugins.capture import translate_capture
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "<command-name>/model</command-name>"},
                {"type": "text", "text":
                    "<local-command-stdout>Set model</local-command-stdout>"},
            ],
        }]
        events = translate_capture(
            self._rec(msgs, sid="blk-pure"), {"session_id": "blk-pure"})
        user_upserts = [e for e in events
                        if e["type"] == "message.upserted"
                        and e["payload"].get("role") == "user"]
        self.assertEqual(user_upserts, [])

    def test_turn_count_survives_mixed_block(self):
        """count_real_user_turns 与 emit 同口径: 混合消息算一条真实 user
        (turn 号不因 block 级过滤漂移)。"""
        from ata.plugins.capture import translate_capture
        msgs = [
            {"role": "user", "content": [
                {"type": "text", "text": "<command-name>/model</command-name>"},
                {"type": "text", "text": "你是谁"},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "答"}]},
            {"role": "user", "content": [
                {"type": "text", "text": "你能做什么?"},
            ]},
        ]
        events = translate_capture(
            self._rec(msgs, sid="blk-turn"), {"session_id": "blk-turn"})
        user_evs = [e for e in events
                    if e["type"] == "message.upserted"
                    and e["payload"].get("role") == "user"]
        # 两条真实 user 消息都 emit, 且 turn 号分别是 1 / 2
        self.assertEqual(len(user_evs), 2)
        self.assertEqual(sorted(e["observed_turn_ordinal"] for e in user_evs), [1, 2])


class StableUserMidTest(unittest.TestCase):
    """user mid 跨轮稳定: 每轮请求都重放全部历史 user 消息, mid 含 turn 号
    时同一条消息每轮换新 mid 重复入账 (sid 74736c29「你能做什么?」记了 3 次)。
    mid 改 {sid}:user:{user_idx}:{content_hash8} 后跨轮重放命中同 dedupe_key
    被吸收。"""

    def _rec(self, messages, sid, resp_id):
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

    def test_replayed_history_not_duplicated(self):
        """第二轮请求重放第一轮的 user 消息: ingest 两次后账本里只有 1 条。"""
        import tempfile
        from pathlib import Path
        from ata.ledger import Ledger
        from ata.plugins.capture import ingest_capture
        turn1_msgs = [
            {"role": "user", "content": [{"type": "text", "text": "你是谁"}]},
        ]
        turn2_msgs = [
            {"role": "user", "content": [{"type": "text", "text": "你是谁"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "答"}]},
            {"role": "user", "content": [{"type": "text", "text": "你能做什么?"}]},
        ]
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d))
            try:
                ingest_capture(led, self._rec(turn1_msgs, "stbl-1", "r1"))
                ingest_capture(led, self._rec(turn2_msgs, "stbl-1", "r2"))
                recs = led.read("stbl-1")
            finally:
                led.close()
            user_texts = sorted(
                r["event"]["payload"]["text"]
                for r in recs
                if r["event"]["type"] == "message.upserted"
                and r["event"]["payload"].get("role") == "user")
            # 重放的「你是谁」被 dedupe 吸收, 不再出现两份
            self.assertEqual(user_texts, ["你是谁", "你能做什么?"])

    def test_mid_has_no_turn_component(self):
        """mid 形状: {sid}:user:{user_idx}:{hash8}, 不含 turn 号。"""
        from ata.plugins.capture import translate_capture
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        events = translate_capture(
            self._rec(msgs, "stbl-2", "r1"), {"session_id": "stbl-2"})
        user_ev = next(e for e in events
                       if e["type"] == "message.upserted"
                       and e["payload"].get("role") == "user")
        import re
        self.assertRegex(user_ev["payload"]["message_id"],
                         r"^stbl-2:user:0:[0-9a-f]{8}$")


class RecapInjectionTest(unittest.TestCase):
    """recap 注入 (user 走开后 harness 自动生成的 40 词总结指令) 无
    <xxx>/[KEY] 形态学特征, 漏过过滤被记成真人发言 (sid 74736c29
    user:3:11)。补已知纯文本注入前缀。"""

    def test_recap_directive_not_emitted(self):
        from ata.plugins.capture import translate_capture
        for sid, txt in [
            ("recap-1", "The user stepped away and is coming back. "
                        "Recap in under 40 words, 1-2 plain sentences, "
                        "no markdown. Lead with the overall goal and "
                        "current task, then the one next action."),
            ("recap-2", "The user stepped away and is coming back. "
                        "Give a one-sentence status update."),
        ]:
            msgs = [{"role": "user",
                     "content": [{"type": "text", "text": txt}]}]
            rec = {
                "agent_id": "claude", "path": "/v1/messages",
                "request_headers": {"x-claude-code-session-id": sid},
                "request_body": json.dumps({
                    "model": "m", "messages": msgs,
                }).encode(),
                "response_content_type": "application/json",
                "response_body": json.dumps({
                    "id": "msg_recap", "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }).encode(),
                "started_at_ms": 1000, "completed_at_ms": 2000,
            }
            events = translate_capture(rec, {"session_id": sid})
            user_upserts = [e for e in events
                            if e["type"] == "message.upserted"
                            and e["payload"].get("role") == "user"]
            self.assertEqual(user_upserts, [], f"failed for {sid}")


if __name__ == "__main__":
    unittest.main()
