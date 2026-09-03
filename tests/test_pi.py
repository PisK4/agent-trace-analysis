import json
import unittest
from pathlib import Path
from ata.plugins.pi import translate_hook, usage_from_assistant

class PiTest(unittest.TestCase):
    def test_extension_lifecycle_contract(self):
        source = Path("extensions/pi-atatrace/index.ts").read_text()
        self.assertIn("crypto.randomUUID()", source)
        self.assertIn('name === "agent_start"', source)
        self.assertIn('name !== "before_agent_start"', source)
        self.assertIn("void postHook", source)
        self.assertIn("lifecycleIds.delete(session_id)", source)

    def test_zero_error_is_missing(self):
        u = usage_from_assistant({
            "usage": {"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"totalTokens":0,"cost":{"total":0}},
            "stopReason": "error",
        })
        self.assertEqual(u["status"], "missing")
        self.assertIsNone(u["input"])

    def test_hook_stream(self):
        hooks = json.loads(Path("testdata/vendor/pi-hooks.json").read_text())
        lifecycle_ids = {
            h["external_lifecycle_id"]
            for h in hooks
            if h.get("name") == "agent_start"
        }
        self.assertEqual(lifecycle_ids, {"pi-lifecycle-1", "pi-lifecycle-2"})
        for h in hooks:
            if h.get("name") not in {"before_agent_start", "agent_start"}:
                self.assertIn(h.get("external_lifecycle_id"), lifecycle_ids)
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
        self.assertIsNone(sys_ev["observed_turn_ordinal"])
        self.assertIn("prompt_text", sys_ev["payload"])
        self.assertEqual([t["name"] for t in sys_ev["payload"]["tools_catalog"]], ["read", "bash"])
        self.assertEqual(sys_ev["payload"]["skills_catalog"][0]["name"], "ata-ops")
        self.assertEqual(
            sys_ev["payload"]["tools_catalog"][0]["parameters"]["properties"]["path"]["type"], "string",
        )
        self.assertIsNone(sys_ev["payload"]["previous_prompt"])
        sys2 = [e for e in evs if e["type"] == "system.upserted"][1]
        self.assertIsNotNone(sys2["payload"]["previous_prompt"])
        self.assertEqual(
            [e["observed_turn_ordinal"] for e in evs if e["type"] == "turn.started"],
            [1, 2],
        )
        self.assertEqual(
            [e["observed_turn_ordinal"] for e in evs if e["type"] == "turn.ended"],
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

    def test_catalog_dedupe(self):
        # 目录逐轮同质化：内容不变不落 tools_catalog / skills_catalog，
        # 内容变化才重新落（投影层负责前向填充）。
        hook = {
            "name": "before_agent_start",
            "event": {"systemPrompt": "p", "systemPromptOptions": {"toolSnippets": {"read": "r"}, "skills": [{"name": "s1"}]}},
            "ctx": {"session_id": "dup"},
        }
        state = {}
        first = translate_hook(hook["name"], hook["event"], hook["ctx"], state)
        self.assertIn("tools_catalog", first[0]["payload"])
        self.assertIn("skills_catalog", first[0]["payload"])
        second = translate_hook(hook["name"], hook["event"], hook["ctx"], state)
        self.assertNotIn("tools_catalog", second[0]["payload"])
        self.assertNotIn("skills_catalog", second[0]["payload"])
        changed = translate_hook("before_agent_start", {
            "systemPrompt": "p",
            "systemPromptOptions": {"toolSnippets": {"read": "r"}, "skills": []},
        }, hook["ctx"], state)
        self.assertIn("skills_catalog", changed[0]["payload"])

    def test_run_transition_resets_accumulators(self):
        # 换档重置归适配器所有：hook 入口只把 runtime 裁决的 run_id 放进 ctx。
        state = {"session_id": "s", "opened": True, "run_id": 1,
                 "turn": 3, "turn_started": 3, "user_pending": False,
                 "last_assistant_id": "a1", "request_no": 5,
                 "tool_args": {"c1": {}}, "tool_start_ts": {"c1": 1}}
        evs = translate_hook("agent_start", {"timestamp": 1},
                             {"session_id": "s", "run_id": 2}, state)
        self.assertEqual(evs, [])
        self.assertEqual(state["run_id"], 2)
        for key in ("turn", "turn_started", "user_pending", "last_assistant_id",
                    "request_no", "tool_args", "tool_start_ts"):
            self.assertNotIn(key, state)
        # 新 Run 的第一条用户消息从 turn 1 起算，不继承上一 Run 的 3
        evs2 = translate_hook("message_start", {"timestamp": 2, "message": {"role": "user", "content": []}},
                              {"session_id": "s"}, state)
        started = [e for e in evs2 if e["type"] == "turn.started"]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["run_id"], 2)
        self.assertEqual(started[0]["turn_number"], 1)

    def test_same_run_redelivery_keeps_accumulators(self):
        state = {"session_id": "s", "opened": True, "run_id": 1, "turn": 2}
        evs = translate_hook("agent_start", {"timestamp": 1},
                             {"session_id": "s", "run_id": 1}, state)
        self.assertEqual(evs, [])
        self.assertEqual(state["turn"], 2)

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
                        "external_lifecycle_id": h.get("external_lifecycle_id"),
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
                self.assertIsNone(sys_row["observed_turn_ordinal"])
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
                httpd.server_close()
                th.join(timeout=2)
                led.close()

if __name__ == "__main__":
    unittest.main()
