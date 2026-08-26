import unittest

from ata.fold import REAL_TS_FLOOR, fold_session_meta


def opened(title="t1", ts=1000, parent=None, sid="s1"):
    p = {"title": title}
    if parent:
        p["parent_session"] = parent
    return {"type": "session.opened", "ts": ts, "turn": None,
            "payload": p, "session_id": sid}


def renamed(title, ts=2000):
    return {"type": "session.renamed", "ts": ts, "turn": None,
            "payload": {"title": title}}


class FoldTest(unittest.TestCase):
    T1 = 1_700_000_000_000
    T2 = 1_700_000_100_000

    def test_new_session_from_opened(self):
        row = fold_session_meta(None, opened(ts=self.T1))
        self.assertEqual(row["title"], "t1")
        self.assertFalse(row["renamed"])
        self.assertEqual(row["first_ts"], self.T1)
        self.assertIsNone(row["parent_session_id"])

    def test_renamed_wins_over_later_opened(self):
        row = fold_session_meta({"title": "user-name", "renamed": True}, opened(title="opened-t"))
        self.assertEqual(row["title"], "user-name")

    def test_opened_overwrites_when_not_renamed(self):
        row = fold_session_meta({"title": "old", "renamed": False}, opened(title="new"))
        self.assertEqual(row["title"], "new")

    def test_dirty_small_ts_not_first_ts(self):
        row = fold_session_meta(None, opened(ts=1))
        self.assertEqual(row["first_ts"], 0)

    def test_first_ts_takes_minimum_real_ts(self):
        row = fold_session_meta(None, opened(ts=self.T2))
        row = fold_session_meta(row, opened(title="t2", ts=self.T1))
        self.assertEqual(row["first_ts"], self.T1)

    def test_parent_preserved_on_non_opened(self):
        row = fold_session_meta({"parent_session_id": "p1"}, renamed("x"))
        self.assertEqual(row["parent_session_id"], "p1")

    def test_parent_updated_on_opened(self):
        row = fold_session_meta({"parent_session_id": "p0"}, opened(parent="p1"))
        self.assertEqual(row["parent_session_id"], "p1")

    def test_bump_turns(self):
        row = fold_session_meta({"turns": 3},
                                {"type": "message.upserted", "ts": 5, "turn": 7, "payload": {}})
        self.assertEqual(row["turns"], 7)

    def test_floor_value(self):
        self.assertEqual(REAL_TS_FLOOR, 10 ** 12)


if __name__ == "__main__":
    unittest.main()
