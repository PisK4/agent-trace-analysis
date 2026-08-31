import os
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.plugins.pi import translate_hook
from ata.schema import parse_event


class CueTest(unittest.TestCase):
    def test_pi_hook_uses_cue_identity(self):
        events = translate_hook(
            "agent_start",
            {"timestamp": 1},
            {
                "session_id": "cue-session",
                "title": "Cue session",
                "agent_id": "cue",
                "host": "cue",
                "runtime": "pi",
                "external_lifecycle_id": "cue-lifecycle-1",
            },
            {},
        )
        event = parse_event(events[0])
        self.assertEqual(event["agent_id"], "cue")
        self.assertEqual(event["payload"]["host"], "cue")
        self.assertEqual(event["payload"]["runtime"], "pi")

    def test_http_hook_preserves_cue_identity(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td))
            httpd = make_server(ledger, Path("web"), "127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                body = {
                    "name": "agent_start",
                    "session_id": "cue-live",
                    "title": "Cue live",
                    "agent_id": "cue",
                    "host": "cue",
                    "runtime": "pi",
                    "external_lifecycle_id": "cue-lifecycle-1",
                    "event": {"timestamp": 1},
                }
                request = urllib.request.Request(
                    f"http://127.0.0.1:{httpd.server_port}/api/pi-hooks",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request) as response:
                    self.assertTrue(json.loads(response.read().decode())["ok"])
                self.assertEqual(ledger.session("cue-live")["agent"], "cue")
                event = ledger.read("cue-live")[0]["event"]
                self.assertEqual(event["payload"]["host"], "cue")
                self.assertEqual(event["payload"]["runtime"], "pi")
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)
                ledger.close()

    def test_http_hook_stamps_arrival_ts_when_event_has_none(self):
        # pi 运行时多数 hook 事件不带 timestamp（类型上只有 turn_start 有），
        # 服务端须用到达时刻兜底，否则 start/end 同 ts、duration 恒 0
        with tempfile.TemporaryDirectory() as td:
            ledger = Ledger(Path(td))
            httpd = make_server(ledger, Path("web"), "127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                def post(name, event):
                    body = {"name": name, "session_id": "ts-fallback", "agent_id": "cue",
                            "event": event}
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{httpd.server_port}/api/pi-hooks",
                        data=json.dumps(body).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        self.assertTrue(json.loads(response.read().decode())["ok"])

                post("message_start", {"type": "message_start",
                                       "message": {"role": "assistant", "content": []}})
                import time as _time
                _time.sleep(0.05)
                post("message_end", {"type": "message_end",
                                     "message": {"role": "assistant",
                                                 "content": [{"type": "text", "text": "ok"}]}})
                # 同 message_id 的 start/end 被 dedupe 收敛成一行，最终行应带
                # 实测耗时（到达时刻差 > 0）
                recs = ledger.read("ts-fallback")
                end = next(r["event"] for r in recs
                           if r["event"]["payload"].get("role") == "assistant")
                self.assertGreaterEqual(end["payload"]["duration_ms"], 1)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)
                ledger.close()

    def test_installer_writes_cue_owned_extension(self):
        with tempfile.TemporaryDirectory() as td:
            agent_dir = Path(td) / "pi-config"
            env = dict(os.environ, CUE_PI_AGENT_DIR=str(agent_dir))
            subprocess.run(
                ["bash", "scripts/attach-cue-pi.sh"],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            target = agent_dir / "extensions" / "ata-cue-trace"
            self.assertIn("ATA_CONFIG", (target / "index.ts").read_text())
            config = (target / "config.ts").read_text()
            self.assertIn('agentId: "cue"', config)
            self.assertIn('host: "cue"', config)
            self.assertIn('runtime: "pi"', config)


if __name__ == "__main__":
    unittest.main()
