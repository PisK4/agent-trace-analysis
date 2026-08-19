#!/usr/bin/env python3
"""Project one local AVA HTTP record into a redacted sketch ledger.

Writes sketches/002-beautiful-workbench/local/ava-window.js (gitignored).
Never copies request/response body, headers, tool arguments, or user text.
One AVA record is a conversation snapshot plus this request's usage, not a Turn.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RECORD_ID = "req_73a9c9673068"
AVA_PATH = Path.home() / ".agent-visual-analysis" / "records.jsonl"
OUT_DIR = Path(__file__).resolve().parent / "local"
OUT_JS = OUT_DIR / "ava-window.js"
OUT_JSON = OUT_DIR / "ava-window.json"


def load_record(path: Path, record_id: str) -> dict:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            if rec.get("id") == record_id:
                return rec
    raise SystemExit(f"record not found: {record_id}")


def usage_projection(raw: object) -> dict:
    if not isinstance(raw, dict) or not raw:
        return {
            "status": "missing",
            "input": None,
            "output": None,
            "cacheRead": None,
            "cacheWrite": None,
            "fields": [],
        }
    input_tokens = raw.get("input_tokens", raw.get("prompt_tokens"))
    output_tokens = raw.get("output_tokens", raw.get("completion_tokens"))
    details = raw.get("input_tokens_details") or raw.get("prompt_tokens_details") or {}
    cache_read = details.get("cached_tokens") if isinstance(details, dict) else None
    numeric = [value for value in (input_tokens, output_tokens, cache_read) if isinstance(value, (int, float))]
    all_zero = bool(numeric) and all(value == 0 for value in numeric)
    status = "missing" if all_zero else "reported"
    return {
        "status": status,
        "input": input_tokens if isinstance(input_tokens, (int, float)) else None,
        "output": output_tokens if isinstance(output_tokens, (int, float)) else None,
        "cacheRead": cache_read if isinstance(cache_read, (int, float)) else None,
        "cacheWrite": None,
        "fields": sorted(raw.keys()),
    }


def redact_item(index: int, item: dict) -> dict:
    role = item.get("role") or "unknown"
    names = [name for name in (item.get("tool_call_names") or []) if isinstance(name, str)]
    types = [name for name in (item.get("content_types") or []) if isinstance(name, str)]
    type_counts: dict[str, int] = {}
    for name in types:
        type_counts[name] = type_counts.get(name, 0) + 1
    return {
        "index": index,
        "role": role,
        "content_types": type_counts,
        "tool_names": names,
        "tool_count": len(names),
    }


def to_rows(items: list[dict], request_usage: dict, response_tools: list[str]) -> list[dict]:
    rows: list[dict] = []
    next_id = 1

    def add(kind: str, label: str, content: str, extra: str = "", usage: dict | None = None, start: bool = False) -> None:
        nonlocal next_id
        rows.append(
            {
                "id": next_id,
                "turn": None,
                "start": start,
                "kind": kind,
                "label": label,
                "content": content,
                "extra": extra,
                "usage": usage
                or {
                    "status": "n/a",
                    "input": None,
                    "output": None,
                    "cacheRead": None,
                    "cacheWrite": None,
                },
                "note": "历史消息属于本次请求体，不是规范 Turn",
            }
        )
        next_id += 1

    add(
        "compact",
        "HTTP",
        "AVA record · 会话快照，不是厂商 Turn",
        "usage 只挂在本次请求",
        {"status": "boundary", "input": None, "output": None, "cacheRead": None, "cacheWrite": None},
        start=True,
    )

    for item in items:
        role = item["role"]
        types = item["content_types"]
        tools = item["tool_names"]
        type_label = " · ".join(f"{name}×{count}" for name, count in types.items()) or "empty"
        if role == "assistant" and tools:
            add("assistant", "Assistant", f"called {len(tools)} tools", type_label)
            counts: dict[str, int] = {}
            for name in tools:
                counts[name] = counts.get(name, 0) + 1
            for name, count in counts.items():
                add("tool", name, "", f"×{count}" if count > 1 else "")
        elif role == "user" and "tool_result" in types:
            add("tool", "Result", "", f"×{types.get('tool_result', 0)}")
        elif role == "system":
            add("compact", "System", type_label)
        elif role == "user":
            add("user", "User", type_label)
        elif role == "assistant":
            add("assistant", "Assistant", type_label)
        else:
            add("compact", role, type_label)

    tool_counts: dict[str, int] = {}
    for name in response_tools:
        tool_counts[name] = tool_counts.get(name, 0) + 1
    tool_label = ", ".join(f"{name}×{count}" if count > 1 else name for name, count in tool_counts.items()) or "no tools"
    add(
        "assistant",
        "Assistant",
        f"this request · {tool_label}",
        "HTTP completion",
        request_usage,
    )
    rows[-1]["note"] = "这是当次 HTTP 请求的 reported usage，不能当成一轮 Turn"
    rows[-1]["start"] = True
    return rows


def main() -> None:
    rec = load_record(AVA_PATH, RECORD_ID)
    request_summary = (rec.get("request") or {}).get("summary") or {}
    response_summary = (rec.get("response") or {}).get("summary") or {}
    conversation = rec.get("conversation") or {}
    source = rec.get("source") or {}
    items = [redact_item(i, item) for i, item in enumerate(request_summary.get("message_items") or []) if isinstance(item, dict)]
    request_usage = usage_projection(response_summary.get("usage"))
    response_tools = [name for name in (response_summary.get("response_tool_call_names") or []) if isinstance(name, str)]
    session_id = conversation.get("session_id") or conversation.get("conversation_id") or ""
    projection = {
        "source": "ava-local-projection",
        "disclaimer": "一条 AVA record 是整段对话快照加当次请求 usage，不是 Atatrace Turn。正文、路径、参数已丢弃。",
        "record_id": RECORD_ID,
        "session_short": (session_id[:8] + "…") if session_id else "unknown",
        "agent": source.get("label") or source.get("agent") or "AVA",
        "model": request_summary.get("model"),
        "api_family": request_summary.get("api_family"),
        "status": rec.get("status"),
        "latency_ms": rec.get("latency_ms"),
        "item_count": len(items),
        "response_tool_count": len(response_tools),
        "request_usage": request_usage,
        "rows": to_rows(items, request_usage, response_tools),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.ATA_LOCAL_PROJECTION = " + json.dumps(projection, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_JS}")
    print(f"wrote {OUT_JSON}")
    print(f"rows={len(projection['rows'])} usage={request_usage} tools={response_tools}")


if __name__ == "__main__":
    main()
