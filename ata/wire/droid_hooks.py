"""Droid CLI hook 事件 → 本地 audit log 落盘。

只追加 JSONL，不入账本。 droid 已有 file watcher 把 transcript 通道
的 event 入账本（plugins/droid.py），这里若再调 ledger.append 会在
file watcher 落账前后产生幂等竞态；audit log 仅供事后分析，先留底。

行格式：
  {"received_at_ms": int,
   "session_id": str | None,
   "hook_event_name": str | None,
   "raw": dict}

append-only；文件不存在自动建，父目录不存在自动 mkdir(parents=True)。
失败不抛（端点 200 必须 fast，PreToolUse 超时 droid 会 AgentAbortError）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def write_hook_event(audit_path: Path, payload: dict) -> None:
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "received_at_ms": int(time.time() * 1000),
                "session_id": payload.get("session_id") if isinstance(payload, dict) else None,
                "hook_event_name": payload.get("hook_event_name") if isinstance(payload, dict) else None,
                "raw": payload,
            }, ensure_ascii=False) + "\n")
            f.flush()
    except Exception as exc:
        # audit log 写失败不能影响 hook 端点 200 返回
        print(f"droid hook audit error: {exc}", flush=True)
