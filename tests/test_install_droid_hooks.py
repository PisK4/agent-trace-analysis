"""Tests for scripts/_merge_droid_hooks.py.

We don't shell-test install-droid-hooks.sh (cross-platform shell quoting is
fragile). Instead we exercise the Python merger directly with subprocess
calls, which is the load-bearing logic — the shell script is a thin wrapper.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MERGE_PY = REPO / "scripts" / "_merge_droid_hooks.py"

ATA_CMD = (
    "(curl -sS -X POST http://127.0.0.1:17877/api/hooks/droid "
    "--data-binary @- --max-time 1 -H 'Content-Type: application/json' &)"
)
EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
    "SessionStart",
]


def _run_merger(*args: str) -> subprocess.CompletedProcess:
    """Invoke the Python merger as a subprocess; return (rc, stdout, stderr)."""
    return subprocess.run(
        [sys.executable, str(MERGE_PY), *args],
        capture_output=True,
        text=True,
    )


def _count_ata_rules(data: dict) -> int:
    """Count the number of ata rules across all 7 events."""
    n = 0
    for ev in EVENTS:
        for rule in data.get(ev) or []:
            for hook in rule.get("hooks", []) or []:
                cmd = hook.get("command") or ""
                if "/api/hooks/droid" in cmd:
                    n += 1
                    break
    return n


class MergeDroidHooksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "hooks.json"

    def tearDown(self):
        self.tmp.cleanup()

    # ---- 1. empty file ----
    def test_empty_file_creates_all_seven_events(self):
        # 不存在的文件: 走 _load_or_empty -> {} -> 全部 event 都被补上
        result = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(self.path.read_text())
        for ev in EVENTS:
            self.assertIn(ev, data, f"{ev} missing")
            self.assertIsInstance(data[ev], list)
            self.assertTrue(data[ev], f"{ev} should have at least one rule")
        self.assertEqual(_count_ata_rules(data), 7)

    def test_empty_string_file_creates_all_seven_events(self):
        self.path.write_text("")
        result = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(self.path.read_text())
        self.assertEqual(_count_ata_rules(data), 7)

    # ---- 2. existing hooks preserved ----
    def test_existing_hooks_preserved(self):
        existing = {
            "PreToolUse": [
                {
                    "matcher": "Read|Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/my-pretool-hook.sh",
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [
                        {"type": "command", "command": "echo done", "timeout": 3}
                    ],
                }
            ],
            "hooksDisabled": False,
            "showHookOutput": True,
        }
        self.path.write_text(json.dumps(existing))

        result = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        data = json.loads(self.path.read_text())

        # 顶层字段保留
        self.assertEqual(data["hooksDisabled"], False)
        self.assertEqual(data["showHookOutput"], True)

        # 用户的 matcher + 已有 command 完整保留
        self.assertEqual(len(data["PreToolUse"]), 2)
        user_rule = data["PreToolUse"][0]
        self.assertEqual(user_rule["matcher"], "Read|Bash")
        self.assertEqual(user_rule["hooks"][0]["command"], "/usr/local/bin/my-pretool-hook.sh")
        # 我们加的在末尾
        ata_rule = data["PreToolUse"][1]
        self.assertNotIn("matcher", ata_rule)
        self.assertEqual(ata_rule["hooks"][0]["command"], ATA_CMD)
        self.assertEqual(ata_rule["hooks"][0]["type"], "command")
        self.assertEqual(ata_rule["hooks"][0]["timeout"], 10)

        # PostToolUse 同样
        self.assertEqual(len(data["PostToolUse"]), 2)
        self.assertEqual(data["PostToolUse"][0]["matcher"], "Write")

        # 其他 5 个 event 都被补上
        for ev in ("Notification", "UserPromptSubmit", "Stop", "SubagentStop", "SessionStart"):
            self.assertIn(ev, data)
            self.assertEqual(len(data[ev]), 1)

        # 总 ata 规则 = 7
        self.assertEqual(_count_ata_rules(data), 7)

    # ---- 3. idempotent ----
    def test_idempotent_no_duplicate(self):
        # 跑两次
        r1 = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(r1.returncode, 0, msg=r1.stderr)
        r2 = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(r2.returncode, 0, msg=r2.stderr)

        data = json.loads(self.path.read_text())
        # 每个 event 只有 1 条 ata rule
        for ev in EVENTS:
            ata_count = sum(
                1
                for rule in data[ev]
                for hook in rule.get("hooks", [])
                if "/api/hooks/droid" in (hook.get("command") or "")
            )
            self.assertEqual(ata_count, 1, f"{ev} has {ata_count} ata rules, want 1")
        # 总 ata 规则 = 7
        self.assertEqual(_count_ata_rules(data), 7)

    # ---- 4. partial installation ----
    def test_partial_installation_idempotent(self):
        # 已经有 3 类 event 被装过
        existing = {}
        for ev in ("PreToolUse", "PostToolUse", "Notification"):
            existing[ev] = [{"hooks": [{"type": "command", "command": ATA_CMD, "timeout": 10}]}]
        # 用户还有一条 PreToolUse rule, 不带 matcher
        existing["PreToolUse"].insert(0, {"hooks": [{"type": "command", "command": "echo hi", "timeout": 2}]})
        self.path.write_text(json.dumps(existing))

        result = _run_merger(ATA_CMD, str(self.path))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        data = json.loads(self.path.read_text())
        # PreToolUse 已有 1 条用户 + 1 条 ata (保留), 没新增第二条 ata
        self.assertEqual(len(data["PreToolUse"]), 2)
        ata_count_pretooluse = sum(
            1
            for rule in data["PreToolUse"]
            for hook in rule.get("hooks", [])
            if "/api/hooks/droid" in (hook.get("command") or "")
        )
        self.assertEqual(ata_count_pretooluse, 1)
        # 总 ata 规则 = 7
        self.assertEqual(_count_ata_rules(data), 7)
        # 后 4 个 event 都被补上
        for ev in ("UserPromptSubmit", "Stop", "SubagentStop", "SessionStart"):
            self.assertIn(ev, data)
            self.assertEqual(len(data[ev]), 1)

    # ---- 5. corrupt JSON ----
    def test_corrupt_json_exits_nonzero(self):
        self.path.write_text("{this is not valid json")
        original = self.path.read_text()
        result = _run_merger(ATA_CMD, str(self.path))
        # 非 0 退出码
        self.assertNotEqual(result.returncode, 0)
        # 文件未被改写 (不破坏)
        self.assertEqual(self.path.read_text(), original)

    # ---- uninstall ----
    def test_uninstall_removes_ata_rules_only(self):
        existing = {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": "echo user", "timeout": 5}],
                },
                {
                    "hooks": [{"type": "command", "command": ATA_CMD, "timeout": 10}],
                },
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": ATA_CMD, "timeout": 10}]}
            ],
        }
        self.path.write_text(json.dumps(existing))

        result = _run_merger("--uninstall", ATA_CMD, str(self.path))
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        data = json.loads(self.path.read_text())
        # PreToolUse 只剩用户那条
        self.assertEqual(len(data["PreToolUse"]), 1)
        self.assertEqual(data["PreToolUse"][0]["matcher"], "Read")
        # Stop 整个 event 被清空 -> 删掉
        self.assertNotIn("Stop", data)
        # 顶层字段没动
        # (这里我们没设顶层字段, 只验证不出现意料外的字段)
        # 任何残留的 ata rule = 0
        self.assertEqual(_count_ata_rules(data), 0)

    # ---- status ----
    def test_status_reports_all_when_full(self):
        # 全部装上
        _run_merger(ATA_CMD, str(self.path))
        result = _run_merger("--status", str(self.path))
        # 全部覆盖 -> 返回 0
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for ev in EVENTS:
            self.assertIn(f"{ev}: ok", result.stdout)

    def test_status_reports_missing_when_empty(self):
        # 没文件
        result = _run_merger("--status", str(self.path))
        # 缺至少一个 -> 返回 1
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        for ev in EVENTS:
            self.assertIn(f"{ev}: missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
