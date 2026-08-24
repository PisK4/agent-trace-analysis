import io, json, tempfile, contextlib, unittest
from pathlib import Path
from ata import cli
from ata.ledger import Ledger


class TestCliRead(unittest.TestCase):
    def setUp(self):
        self.led_dir = Path(tempfile.mkdtemp())
        led = Ledger(self.led_dir / "t.sqlite")
        led.append({"v": 1, "id": "o1", "agent_id": "pi", "session_id": "s1",
                    "ts": 1000, "type": "session.opened", "turn": None,
                    "payload": {"title": "demo"}})

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["read", *argv, "--ledger", str(self.led_dir / "t.sqlite")])
        return json.loads(buf.getvalue())

    def test_sessions_local_mode(self):
        out = self.run_cli("sessions")
        self.assertEqual(out["sessions"][0]["id"], "s1")

    def test_usage_local_mode_shape(self):
        out = self.run_cli("usage", "s1")
        self.assertEqual(out["total"], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0})


if __name__ == "__main__":
    unittest.main()
