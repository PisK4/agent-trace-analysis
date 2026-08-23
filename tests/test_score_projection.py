import unittest
from ata.project import project_session


def rec(seq, typ, payload, turn=None):
    return {"seq": seq, "event": {"v": 1, "id": f"e{seq}", "agent_id": "cue",
            "session_id": "s", "ts": seq * 1000, "type": typ, "turn": turn,
            "payload": payload}}


class TestScoreProjection(unittest.TestCase):
    def test_scores_in_order_with_notes(self):
        recs = [
            rec(1, "session.opened", {"title": "t"}),
            rec(2, "session.scored", {"value": "bad", "note": "方向跑偏"}),
            rec(3, "message.upserted", {"message_id": "m1", "role": "user",
                                        "text": "hi", "status": "completed",
                                        "started_at": 3000}, turn=1),
            rec(4, "session.scored", {"value": "good"}),
        ]
        page = project_session("s", "cue", recs)
        self.assertEqual(page["scores"], [
            {"value": "bad", "note": "方向跑偏", "ts": 2000},
            {"value": "good", "note": None, "ts": 4000},
        ])
        # 标注不混进内容行
        self.assertTrue(all(row["kind"] != "score" for row in page["rows"]))

    def test_no_scores_is_empty_list(self):
        page = project_session("s", "cue", [rec(1, "session.opened", {"title": "t"})])
        self.assertEqual(page["scores"], [])

    def test_tail_window_keeps_all_scores(self):
        recs = [
            rec(1, "session.opened", {"title": "t"}),
            rec(2, "session.scored", {"value": "partial", "note": "一半可用"}),
            rec(3, "session.scored", {"value": "bad"}),
        ]
        page = project_session("s", "cue", recs, tail=1)
        self.assertEqual(len(page["scores"]), 2)


if __name__ == "__main__":
    unittest.main()
