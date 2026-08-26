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
        h = {"x-claude-code-session-id": "abc-123"}
        self.assertEqual(resolve_session_id(h, "claude"), "abc-123")

    def test_missing_header_returns_none(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"user-agent": "claude-cli"}, "claude"))

    def test_none_safe(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"request_headers": None}, "claude"))


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
