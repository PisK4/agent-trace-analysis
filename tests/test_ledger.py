import tempfile
import unittest
from pathlib import Path

from ata.ledger import Ledger
from ata.schema import parse_event

EV = parse_event({
    "v": 1, "id": "e1", "agent_id": "pi", "session_id": "s1",
    "ts": 10, "type": "session.opened", "turn": None,
    "payload": {"title": "hello"},
})


class LedgerTest(unittest.TestCase):
    def test_append_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            a = led.append(EV)
            b = led.append(EV)
            self.assertEqual(a, 1)
            self.assertEqual(b, 1)
            self.assertEqual(len(led.read("s1")), 1)

    def test_unknown_session_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(Ledger(Path(td)).read("nope"), [])

    def test_session_title_comes_from_index(self):
        with tempfile.TemporaryDirectory() as td:
            led = Ledger(Path(td))
            led.append(EV)
            listing = led.sessions()
            self.assertEqual(listing, [{
                "id": "s1",
                "agent": "pi",
                "title": "hello",
                "turns": 0,
            }])


if __name__ == "__main__":
    unittest.main()
