import json
import unittest
from pathlib import Path
from ata.plugins.pi import translate_hook, usage_from_assistant

class PiTest(unittest.TestCase):
    def test_zero_error_is_missing(self):
        u = usage_from_assistant({
            "usage": {"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},
            "stopReason": "error",
        })
        self.assertEqual(u["status"], "missing")
        self.assertIsNone(u["input"])

    def test_hook_stream(self):
        hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
        evs = []
        state = {}
        for h in hooks:
            evs.extend(translate_hook(h["name"], h["event"], h.get("ctx") or {}, state))
        types = [e["type"] for e in evs]
        self.assertEqual(types[0], "session.opened")
        self.assertIn("tool.upserted", types)
        last = [e for e in evs if e["type"]=="turn.ended"][-1]
        self.assertEqual(last["payload"]["usage"]["status"], "missing")

if __name__ == "__main__":
    unittest.main()
