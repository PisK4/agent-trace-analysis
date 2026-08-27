#!/usr/bin/env python3
"""Merge ATA's droid hook commands into a hooks.json file.

This is invoked by `install-droid-hooks.sh` and is a pure-Python helper so
the shell script can stay small. Behavior:

  * load existing JSON (or {} if missing/empty)
  * for each of the 7 droid hook events, ensure an ata command rule is present
  * never delete or rewrite user rules (matcher, other hooks, top-level fields
    like hooksDisabled/showHookOutput are preserved as-is)
  * idempotent: re-running won't duplicate the ata rule
  * corrupt JSON: print diagnostic to stderr and exit 2, leaving the file
    untouched (caller decides whether to back it up + retry)

CLI:
  _merge_droid_hooks.py <command> <hooks.json path>
      - install mode: append ata command to every event
  _merge_droid_hooks.py --uninstall <command> <hooks.json path>
      - remove ata command (matched by /api/hooks/droid substring) from
        every event, then strip empty rules/events
  _merge_droid_hooks.py --status <hooks.json path>
      - print a one-line-per-event report; exit 0 if every event has ata,
        1 otherwise (handy for shell --status flag)

The <command> string is a shell snippet ATA wants to invoke. For install mode
it must be a single command (the merger wraps it in {"hooks": [...]}). For
uninstall mode the same string is used to identify which rules to strip —
any rule whose hooks[*].command contains both '/api/hooks/droid' AND
<command>'s host/port is considered "ours".
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "UserPromptSubmit",
    "Stop",
    "SubagentStop",
    "SessionStart",
]

ATA_MARKER = "/api/hooks/droid"


def _ata_command_for(rule_command: str) -> str:
    """Build the hook command string. The shell snippet already encodes
    ATA_URL, so we just embed it verbatim into a command field."""
    return rule_command


def _has_ata_rule(rules: list[dict], marker: str) -> bool:
    """True if any rule in the list already has an ata command."""
    for rule in rules:
        for hook in rule.get("hooks", []) or []:
            cmd = hook.get("command") or ""
            if marker in cmd and "/api/hooks/droid" in cmd:
                return True
    return False


def _is_ata_rule(rule: dict, marker: str) -> bool:
    """A rule is 'ours' if it has at least one hook with the marker."""
    if not isinstance(rule, dict):
        return False
    for hook in rule.get("hooks", []) or []:
        cmd = hook.get("command") or ""
        if marker in cmd and "/api/hooks/droid" in cmd:
            return True
    return False


def _load_or_empty(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(data, dict):
        print(f"error: {path} must be a JSON object at top level, got {type(data).__name__}", file=sys.stderr)
        sys.exit(2)
    return data


def install(path: Path, command: str) -> dict:
    """Append ata rule to every event; preserve everything else."""
    data = _load_or_empty(path)
    new_rule = {
        "hooks": [
            {
                "type": "command",
                "command": _ata_command_for(command),
                "timeout": 10,
            }
        ]
    }
    for ev in EVENTS:
        rules = data.get(ev)
        if rules is None:
            rules = []
        if not isinstance(rules, list):
            # 用户写了非 list 值, 我们不强行覆盖, 但提示
            print(f"warning: {ev} is not a list in {path}; skipping", file=sys.stderr)
            continue
        if not _has_ata_rule(rules, command):
            rules.append(new_rule)
        data[ev] = rules
    return data


def uninstall(path: Path, command: str) -> dict:
    """Remove ata rules (matched by marker) from every event; drop empty
    events so the JSON stays clean."""
    data = _load_or_empty(path)
    for ev in EVENTS:
        rules = data.get(ev)
        if not isinstance(rules, list):
            continue
        kept = [r for r in rules if not _is_ata_rule(r, command)]
        if kept:
            data[ev] = kept
        else:
            # 没东西了: 整个 event 删掉
            data.pop(ev, None)
    return data


def status(path: Path, command: str | None = None) -> int:
    """Print one line per event; return 0 if all 7 have ata, 1 otherwise.

    `command` is unused in --status mode (we just need the marker substring
    which is always '/api/hooks/droid'); kept for API symmetry with the
    other helpers.
    """
    if not path.exists():
        print(f"status: {path} does not exist (no hooks.json)")
        for ev in EVENTS:
            print(f"  {ev}: missing")
        return 1
    data = _load_or_empty(path)
    all_ok = True
    for ev in EVENTS:
        rules = data.get(ev) or []
        ok = _has_ata_rule(rules, ATA_MARKER)
        if not ok:
            all_ok = False
        mark = "ok" if ok else "missing"
        print(f"  {ev}: {mark}")
    return 0 if all_ok else 1


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _merge_droid_hooks.py [--uninstall|--status] <command> <path>", file=sys.stderr)
        return 2
    if argv[1] == "--status":
        if len(argv) != 3:
            print("usage: _merge_droid_hooks.py --status <path>", file=sys.stderr)
            return 2
        path = Path(argv[2])
        return status(path)
    if argv[1] == "--uninstall":
        if len(argv) != 4:
            print("usage: _merge_droid_hooks.py --uninstall <command> <path>", file=sys.stderr)
            return 2
        command = argv[2]
        path = Path(argv[3])
        data = uninstall(path, command)
        _write(path, data)
        print(f"uninstalled ata hooks from {path}")
        return 0
    # install mode
    if len(argv) != 3:
        print("usage: _merge_droid_hooks.py <command> <path>", file=sys.stderr)
        return 2
    command = argv[1]
    path = Path(argv[2])
    data = install(path, command)
    _write(path, data)
    print(f"installed ata hooks into {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
