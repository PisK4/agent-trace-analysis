import unittest

from ata.plugins.capture import count_real_user_turns, resolve_session_id


def user_msg(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


class ResolveSessionTest(unittest.TestCase):
    def test_claude_header_case_insensitive(self):
        h = {"x-claude-code-session-id": "abc-123"}
        self.assertEqual(resolve_session_id(h, "claude"), "abc-123")

    def test_missing_header_returns_none(self):
        self.assertIsNone(resolve_session_id({}, "claude"))
        self.assertIsNone(resolve_session_id({"user-agent": "claude-cli"}, "claude"))


class CountTurnsTest(unittest.TestCase):
    def test_counts_real_user_messages(self):
        msgs = [
            user_msg("first"),
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            user_msg("second"),
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            user_msg("third"),
        ]
        self.assertEqual(count_real_user_turns(msgs), 3)

    def test_context_injection_does_not_count(self):
        msgs = [
            user_msg("first"),
            user_msg("<system-reminder>context noise</system-reminder>"),
            user_msg("second"),
        ]
        self.assertEqual(count_real_user_turns(msgs), 2)

    def test_empty_and_malformed(self):
        self.assertEqual(count_real_user_turns([]), 0)
        self.assertEqual(count_real_user_turns([{"role": "user"}, None, "junk"]), 0)


if __name__ == "__main__":
    unittest.main()
