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
