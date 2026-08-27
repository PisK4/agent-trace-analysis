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
    def test_droid_header_x_droid_session_id(self):
        # 2026-08-27: capture_proxy e2e 验证 droid 走 `x-droid-session-id` 头能
        # 恢复 sid（真实 droid exec 客户端在 17878 上发请求, capture_proxy 把
        # 该头过白名单后由 resolve_session_id 命中）。
        rec = {
            "request_headers": {"x-droid-session-id": "d-sid-1"},
            "request_body": b'{"unrelated": "json"}',
        }
        self.assertEqual(resolve_session_id(rec, "droid"), "d-sid-1")

    def test_droid_body_metadata_session_id(self):
        # droid 走 OpenAI Chat Completions 也可能在 body 放 metadata.session_id
        # （与 codex 平行）。两条路径都声明,任一命中都恢复 sid。
        rec = {
            "request_headers": {"x-droid-trace-id": "ignored"},
            "request_body": b'{"metadata": {"session_id": "d-sid-2"}}',
        }
        self.assertEqual(resolve_session_id(rec, "droid"), "d-sid-2")

    def test_droid_header_takes_precedence_over_body(self):
        # 与 codex 同款:header 路径先匹配,命中即返回(不再走 body 路径)。
        rec = {
            "request_headers": {"x-droid-session-id": "from-header"},
            "request_body": b'{"metadata": {"session_id": "from-body"}}',
        }
        self.assertEqual(resolve_session_id(rec, "droid"), "from-header")

    def test_droid_no_match_returns_none(self):
        # droid 头/body 都不命中(其他 x-droid-* 头、缺 metadata)→ None。
        rec = {
            "request_headers": {"x-droid-trace-id": "x"},
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
        self.assertEqual([e["type"] for e in evs], ["system.upserted", "turn.ended"])
        sys_ev, end_ev = (self.parse_event(e) for e in evs)
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
        r = record(json.dumps(REQ1).encode(), json.dumps(RESP1).encode())
        self.translate(r, self.state)
        evs = self.translate(r, self.state)
        self.assertEqual([e["type"] for e in evs], ["turn.ended"])

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
        _, end = (self.parse_event(e) for e in self.translate(
            record(json.dumps(req2).encode(), json.dumps(RESP1).encode()),
            self.state))
        self.assertEqual(end["turn"], 2)

    def test_missing_usage_emits_nothing(self):
        resp = dict(RESP1, usage={})
        evs = self.translate(record(json.dumps(REQ1).encode(),
                                    json.dumps(resp).encode()), self.state)
        # system 快照仍要发；turn.ended 没有 usage 就不发
        self.assertEqual([e["type"] for e in evs], ["system.upserted"])

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


if __name__ == "__main__":
    unittest.main()
