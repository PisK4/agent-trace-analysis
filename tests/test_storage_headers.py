import unittest

from ata.wire.storage_headers import (
    STORAGE_HEADER_NAMESPACES,
    record_headers_for_storage,
)


class NamespacesDeclaredTest(unittest.TestCase):
    def test_three_agent_namespaces(self):
        # claude / codex / droid 三家 namespace 都声明了。droid 暂未列出具体头，
        # 但 namespace 占位存在（等真实流量回填）。
        self.assertIn("x-claude-", STORAGE_HEADER_NAMESPACES)
        self.assertIn("x-codex-", STORAGE_HEADER_NAMESPACES)
        self.assertIn("x-droid-", STORAGE_HEADER_NAMESPACES)


class WhitelistTest(unittest.TestCase):
    def test_claude_session_id_kept(self):
        h = {"X-Claude-Code-Session-Id": "s1", "Authorization": "sk-x"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"X-Claude-Code-Session-Id": "s1"})

    def test_codex_window_id_kept(self):
        h = {"x-codex-window-id": "win-1", "user-agent": "codex-cli"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"x-codex-window-id": "win-1"})

    def test_droid_namespace_kept(self):
        h = {"x-droid-trace-id": "d1", "x-droid-build": "1.0"}
        out = record_headers_for_storage(h)
        self.assertEqual(out, {"x-droid-trace-id": "d1", "x-droid-build": "1.0"})

    def test_undeclared_header_dropped(self):
        # 不在三家 namespace 内的头一律不落档（认证头/通用协议头不进账本）。
        h = {"authorization": "sk-x", "x-api-key": "sk-y", "user-agent": "x",
             "content-type": "application/json"}
        self.assertEqual(record_headers_for_storage(h), {})

    def test_case_insensitive_match(self):
        h = {"X-CLAUDE-CODE-SESSION-ID": "s1"}
        self.assertEqual(
            record_headers_for_storage(h), {"X-CLAUDE-CODE-SESSION-ID": "s1"})

    def test_empty_headers(self):
        self.assertEqual(record_headers_for_storage({}), {})

    def test_none_safe(self):
        self.assertEqual(record_headers_for_storage(None), {})

    def test_returns_dict_copy(self):
        # 改返回值不影响入参。
        h = {"x-claude-code-session-id": "s1"}
        out = record_headers_for_storage(h)
        out["x-claude-code-session-id"] = "modified"
        self.assertEqual(h["x-claude-code-session-id"], "s1")
