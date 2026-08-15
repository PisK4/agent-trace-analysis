import unittest
from pathlib import Path
from ata.plugins.droid import translate_file
from ata.project import project_session

class DroidTest(unittest.TestCase):
    def test_maps_verified_types(self):
        evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
        types = [e["type"] for e in evs]
        self.assertIn("session.opened", types)
        self.assertIn("message.upserted", types)
        self.assertIn("tool.upserted", types)
        self.assertIn("turn.ended", types)
        self.assertNotIn("compaction.boundary", types)
        recs = [{"seq": i+1, "event": e} for i, e in enumerate(evs)]
        sess = project_session("droid-missing", "droid", recs)
        asst = next(r for r in sess["rows"] if r["kind"] == "assistant")
        self.assertEqual(asst["usage"]["status"], "missing")
        tool = next(r for r in sess["rows"] if r["kind"] == "tool")
        self.assertEqual(tool["name"], "Read")

if __name__ == "__main__":
    unittest.main()
