import unittest

from ata.__main__ import resolve_proxy_upstream


class ProxyUpstreamTest(unittest.TestCase):
    def test_claude_default_upstream(self):
        self.assertEqual(
            resolve_proxy_upstream("claude", None),
            "https://api.anthropic.com",
        )

    def test_codex_default_upstream(self):
        self.assertEqual(
            resolve_proxy_upstream("codex", None),
            "https://api.openai.com",
        )

    def test_explicit_upstream_wins(self):
        self.assertEqual(
            resolve_proxy_upstream("codex", "http://127.0.0.1:9000"),
            "http://127.0.0.1:9000",
        )


if __name__ == "__main__":
    unittest.main()
