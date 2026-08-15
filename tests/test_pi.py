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
        self.assertEqual(types[0], "system.upserted")
        self.assertEqual(types.count("system.upserted"), 2)
        self.assertIn("session.opened", types)
        self.assertNotIn("session.closed", types)
        sys_ev = next(e for e in evs if e["type"] == "system.upserted")
        self.assertIsNone(sys_ev["turn"])
        self.assertIn("prompt_text", sys_ev["payload"])
        self.assertEqual([t["name"] for t in sys_ev["payload"]["tools_catalog"]], ["read", "bash"])
        self.assertIsNone(sys_ev["payload"]["previous_prompt"])
        sys2 = [e for e in evs if e["type"] == "system.upserted"][1]
        self.assertIsNotNone(sys2["payload"]["previous_prompt"])
        self.assertEqual(
            [e["turn"] for e in evs if e["type"] == "turn.started"],
            [1, 2],
        )
        self.assertEqual(
            [e["turn"] for e in evs if e["type"] == "turn.ended"],
            [1, 2],
        )
        last_end = [e for e in evs if e["type"] == "turn.ended"][-1]
        self.assertEqual(last_end["payload"]["usage"]["status"], "reported")
        title_ev = next(
            e for e in evs
            if e["type"] == "session.opened" and e["payload"]["title"] == "ask about usage"
        )
        self.assertIsNotNone(title_ev)
        tools = [e for e in evs if e["type"] == "tool.upserted"]
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[-1]["payload"]["status"], "completed")
        self.assertEqual(tools[-1]["payload"]["text"], "f")
        users = [e for e in evs if e["type"] == "message.upserted" and e["payload"]["role"] == "user"]
        self.assertEqual(
            {e["payload"]["message_id"] for e in users},
            {"pi-compact:1:user", "pi-compact:2:user"},
        )
        asst_done = [
            e for e in evs
            if e["type"] == "message.upserted" and e["payload"]["role"] == "assistant" and e["payload"]["status"] == "completed"
        ]
        self.assertTrue(all(e["payload"]["text"] for e in asst_done))
        self.assertIn("need to answer concisely", asst_done[0]["payload"]["text"])

    def test_hook_http_pipe(self):
        import json
        import tempfile
        import threading
        import urllib.request
        from pathlib import Path
        from ata.http import make_server
        from ata.ledger import Ledger

        hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            httpd = make_server(led, Path("web"), "127.0.0.1", 0)
            th = threading.Thread(target=httpd.serve_forever, daemon=True)
            th.start()
            try:
                for h in hooks:
                    body = {
                        "name": h["name"],
                        "session_id": (h.get("ctx") or {}).get("session_id") or "pi-compact",
                        "title": (h.get("ctx") or {}).get("title") or "synthetic pi turn",
                        "event": h["event"],
                    }
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/pi-hooks",
                        data=json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req) as r:
                        self.assertTrue(json.loads(r.read().decode())["ok"])
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/sessions/pi-compact") as r:
                    page = json.loads(r.read().decode())
                self.assertEqual(page["title"], "ask about usage")
                self.assertEqual(page["turns"], 2)
                kinds = [row["kind"] for row in page["rows"]]
                self.assertIn("user", kinds)
                self.assertIn("assistant", kinds)
                self.assertIn("tool", kinds)
                self.assertIn("system", kinds)
                sys_row = next(row for row in page["rows"] if row["kind"] == "system")
                self.assertIsNone(sys_row["turn"])
                self.assertIn("You are Pi", sys_row["promptText"])
                self.assertEqual([t["name"] for t in sys_row["toolsCatalog"]], ["read", "bash"])
                users = [row for row in page["rows"] if row["kind"] == "user"]
                self.assertEqual(
                    [row["text"] for row in users],
                    ["ask about usage", "help update plugins"],
                )
                tool = next(row for row in page["rows"] if row["kind"] == "tool")
                self.assertEqual(tool["status"], "completed")
                self.assertEqual(tool["result"], "ok")
                self.assertTrue(all(row["status"] != "pending" for row in page["rows"]))
                asst = [row for row in page["rows"] if row["kind"] == "assistant"]
                self.assertTrue(all(row["text"] for row in asst))
                self.assertEqual(asst[0]["usage"]["status"], "reported")
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/sessions") as r:
                    listing = json.loads(r.read().decode())
                listed = next(x for x in listing if x["id"] == "pi-compact")
                self.assertEqual(listed["title"], "ask about usage")
                self.assertEqual(listed["turns"], 2)
            finally:
                httpd.shutdown()

if __name__ == "__main__":
    unittest.main()
