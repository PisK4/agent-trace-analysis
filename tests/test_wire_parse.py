import unittest

from ata.wire import parse_request, parse_response


REQ = (
    b'{"model":"claude-sonnet-5","stream":false,'
    b'"system":[{"type":"text","text":"You are ATA."}],'
    b'"tools":[{"name":"Read","description":"read a file",'
    b'"input_schema":{"type":"object"}}],'
    b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
)

RESP = (
    b'{"id":"msg_01","type":"message","role":"assistant",'
    b'"content":[{"type":"text","text":"hello"}],"stop_reason":"end_turn",'
    b'"usage":{"input_tokens":10,"output_tokens":5,'
    b'"cache_read_input_tokens":2,"cache_creation_input_tokens":1}}'
)


class WireParseTest(unittest.TestCase):
    def test_request_path_dispatch(self):
        s = parse_request("/v1/messages", {}, REQ)
        self.assertEqual(s["parser"]["family"], "anthropic-messages")
        self.assertEqual(s["parser"]["version"], 2)
        self.assertTrue(s["json_valid"])
        self.assertEqual(s["system_prompts"], ["You are ATA."])
        self.assertEqual([t["name"] for t in s["tool_items"]], ["Read"])

    def test_non_messages_path_falls_back(self):
        s = parse_request("/v1/unknown", {}, REQ)
        self.assertEqual(s["parser"]["family"], "openai-compatible")

    def test_response_json(self):
        s = parse_response("/v1/messages", {}, "application/json", RESP)
        self.assertEqual(s["response_id"], "msg_01")
        self.assertEqual(s["response_text"], "hello")
        self.assertEqual(s["usage"]["input_tokens"], 10)

    def test_response_sse_accumulates_blocks(self):
        body = (
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_02","usage":{"input_tokens":7}}}\n\n'
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n\n'
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"he"}}\n\n'
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"y"}}\n\n'
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
        )
        s = parse_response("/v1/messages", {}, "text/event-stream", body)
        self.assertEqual(s["response_id"], "msg_02")
        self.assertEqual(s["response_text"], "hey")
        self.assertEqual(s["usage"], {"input_tokens": 7, "output_tokens": 3})

    def test_garbage_body_never_raises(self):
        s = parse_request("/v1/messages", {}, b"not json")
        self.assertFalse(s["json_valid"])
        s2 = parse_response("/v1/messages", {}, "application/json", b"\xff\xfe")
        self.assertFalse(s2["json_valid"])


if __name__ == "__main__":
    unittest.main()
