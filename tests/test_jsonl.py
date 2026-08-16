import tempfile
import time
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.plugins.claude import translate_file
from ata.plugins.jsonl import step_tail


def _line(typ, mid, text):
    import json
    return json.dumps({
        "type": typ, "uuid": mid, "sessionId": "tail-sess",
        "timestamp": "2026-08-16T10:00:00Z",
        "message": {"role": "user" if typ == "user" else "assistant", "content": [{"type": "text", "text": text}]},
    }) + "\n"


class JsonlTailTest(unittest.TestCase):
    def test_directory_tail_discovers_new_and_appended_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            # 第一轮：目录里一个文件
            (root / "a.jsonl").write_text(_line("user", "u1", "first"))
            batch1 = step_tail(root, translate_file, led, state)
            self.assertTrue(any(e["type"] == "message.upserted" for e in batch1))
            # 第二轮：既有文件追加 + 新文件出现
            with open(root / "a.jsonl", "a") as f:
                f.write(_line("assistant", "a1", "reply"))
            (root / "b.jsonl").write_text(_line("user", "u2", "second"))
            step_tail(root, translate_file, led, state)
            self.assertEqual(len(led.sessions()), 1)
            events = led.read("tail-sess")
            ev_ids = [r["event"]["id"] for r in events]
            # 幂等账本无重复：opened / turn:1:start / u1 / a1 / u2
            self.assertEqual(len(ev_ids), len(set(ev_ids)))
            self.assertEqual(len(events), 5)
            mids = {r["event"]["payload"]["message_id"] for r in events if r["event"]["type"] == "message.upserted"}
            self.assertEqual(mids, {"u1", "a1", "u2"})

    def test_max_age_days_skips_historical_files(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            led = Ledger(root / "ledger")
            state = {}
            new = root / "new.jsonl"
            new.write_text(_line("user", "u-new", "recent"))
            old = root / "old.jsonl"
            old.write_text(_line("user", "u-old", "ancient"))
            past = time.time() - 30 * 86400
            os.utime(old, (past, past))
            step_tail(root, translate_file, led, state, max_age_days=7)
            mids = {r["event"]["payload"]["message_id"] for r in led.read("tail-sess")
                    if r["event"]["type"] == "message.upserted"}
            self.assertEqual(mids, {"u-new"})


if __name__ == "__main__":
    unittest.main()
