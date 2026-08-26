from __future__ import annotations

from datetime import datetime

from ata.plugins.common import (
    PLACEHOLDER_MS,
    bump_turn_if_real_user,
    is_context_text,
    make_ev,
    tool_end_payload,
    tool_start_payload,
    usage_from_counts,
    usage_missing,
)
from ata.plugins.jsonl import translate_file as _jfile


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    session_id = raw.get("sessionId") or state.get("session_id") or "claude-session"
    state["session_id"] = session_id
    agent_id = "claude"
    ts = _ts(raw, state)
    state["ts"] = ts
    out = []
    if not state.get("opened"):
        state["opened"] = True
        out.append(make_ev(
            f"{session_id}:opened", agent_id, session_id, ts,
            "session.opened", None, {"title": session_id},
        ))
    if typ == "ai-title":
        title = str(raw.get("aiTitle") or "").strip()
        if title:
            out.append(make_ev(
                f"{session_id}:opened:title", agent_id, session_id, ts,
                "session.opened", None, {"title": title[:80]},
            ))
        return out
    if typ == "system":
        return _system_line(raw, state, ts, out)
    if typ not in {"user", "assistant"}:
        return out
    msg = raw.get("message")
    if isinstance(msg, str):
        content = msg
        role = typ
    elif isinstance(msg, dict):
        content = msg.get("content") or ""
        role = msg.get("role")
    else:
        return out
    if role not in {"user", "assistant"}:
        return out
    texts, thinking = _split(content)
    is_tool_only = role == "user" and texts == "" and _has_tool_result(content)
    if not is_tool_only:
        if role == "user" and not is_context_text(texts):
            # Claude transcript 没有显式 turn 事件：轮次按真实用户消息递增（同 droid）。
            # CONTEXT 注入（system-reminder / Skill）不另开一轮。
            bump_turn_if_real_user(state, texts, agent_id, session_id, ts,
                                   lambda e: out.append(e))
            turn = state.get("turn") or 1
            state["last_assistant_id"] = None
        else:
            turn = state.get("turn") or 1
            state["turn"] = turn
            state["last_assistant_id"] = str(msg.get("id") or raw.get("uuid") or f"{session_id}:asst:{ts}")
            state["request_no"] = int(state.get("request_no") or 0) + 1
        # 消息行 id：assistant 用 API message id（msg_…），user 行 message 无 id 用行级 uuid。
        mid = str(msg.get("id") or raw.get("uuid") or f"{session_id}:{role}:{ts}")
        usage = _usage(msg) if role == "assistant" else None
        model = msg.get("model") if isinstance(msg, dict) else None
        if isinstance(model, str) and (not model or model.startswith("<")):
            model = None
        out.append(make_ev(
            f"{session_id}:msg:{mid}", agent_id, session_id, ts,
            "message.upserted", state.get("turn") or 1,
            {
                "message_id": mid,
                "role": role,
                "text": (texts or "")[:200],
                "status": "completed",
                "request_no": state.get("request_no") if role == "assistant" else None,
                "usage": usage,
                "started_at": ts,
                "duration_ms": PLACEHOLDER_MS,
                "output_text": texts if role == "assistant" else None,
                "thinking": thinking or None,
                "model": model,
            },
        ))
    for block in _blocks(content):
        if block.get("type") == "tool_use":
            cid = str(block.get("id") or "")
            if not cid:
                continue
            name = block.get("name") or "tool"
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            payload = tool_start_payload(
                cid, state.get("last_assistant_id"), name, args,
                _tool_text(name, args), ts)
            state.setdefault("tools", {})[cid] = payload
            # 与 droid / pi 同款：start/end 拆两个 event id，幂等账本才收得到完成态。
            out.append(make_ev(
                f"{session_id}:tool:{cid}:start", agent_id, session_id, ts,
                "tool.upserted", state.get("turn") or 1,
                payload,
            ))
        elif block.get("type") == "tool_result":
            cid = str(block.get("tool_use_id") or block.get("id") or "")
            if not cid:
                continue
            result = _result_text(block.get("content"))
            prev = state.setdefault("tools", {}).get(cid, {})
            end_payload = tool_end_payload(prev, cid, state.get("last_assistant_id"), result, ts)
            out.append(make_ev(
                f"{session_id}:tool:{cid}:end", agent_id, session_id, ts,
                "tool.upserted", state.get("turn") or 1,
                end_payload,
            ))
    return out


def translate_file(path, offset: int = 0):
    return _jfile(path, translate_line, offset)


def _system_line(raw, state, ts, out):
    sub = raw.get("subtype")
    session_id = state["session_id"]
    turn = state.get("turn") or 1
    state["turn"] = turn
    if sub == "compact_boundary":
        meta = raw.get("compactMetadata") if isinstance(raw.get("compactMetadata"), dict) else {}
        cid = str(raw.get("uuid") or ts)
        out.append(make_ev(
            f"{session_id}:compact:{cid}", "claude", session_id, ts,
            "compaction.boundary", turn,
            {
                "summary": "Context compacted",
                "trigger": meta.get("trigger"),
                "pre_tokens": meta.get("preTokens"),
                "post_tokens": meta.get("postTokens"),
                "duration_ms": meta.get("durationMs"),
            },
        ))
        return out
    if sub == "api_error":
        err = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        bits = ["api_error"]
        if err.get("status") is not None:
            bits.append(str(err["status"]))
        attempt, max_r = raw.get("retryAttempt"), raw.get("maxRetries")
        if attempt is not None and max_r is not None:
            bits.append(f"retry {attempt}/{max_r}")
        mid = str(raw.get("uuid") or f"{session_id}:api-error:{turn}:{ts}")
        out.append(make_ev(
            f"{session_id}:msg:{mid}", "claude", session_id, ts,
            "message.upserted", turn,
            {
                "message_id": mid,
                "role": "assistant",
                "text": " · ".join(bits),
                "status": "failed",
                "request_no": None,
                "usage": None,
                "started_at": ts,
                "duration_ms": PLACEHOLDER_MS,
                "output_text": " · ".join(bits),
                "thinking": None,
            },
        ))
    return out


def _ts(raw, state):
    s = raw.get("timestamp") or raw.get("ts")
    if s:
        if isinstance(s, (int, float)):
            return int(s) if s > 10**12 else int(s * 1000)
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return int(state.get("ts") or 1)


def _blocks(content):
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _split(content):
    """把 content 拆成 (正文, thinking)。text 只含文本块，thinking 单独出字段，
    供前端折叠展示（dsh 的 thinking 折叠同款）。老格式的裸字符串文本块归正文。
    """
    if isinstance(content, str):
        return content, ""
    texts, thinking = [], []
    for b in _blocks(content):
        if b.get("type") == "text" and b.get("text"):
            texts.append(str(b["text"]))
        elif b.get("type") == "thinking" and b.get("thinking"):
            thinking.append(str(b["thinking"]))
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                texts.append(b)
    return "\n".join(texts), "\n".join(thinking)


def _texts(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in _blocks(content):
        if b.get("type") == "text" and b.get("text"):
            parts.append(str(b["text"]))
        elif b.get("type") == "thinking" and b.get("thinking"):
            parts.append(str(b["thinking"]))
    # 老格式 transcript 的 content 数组里可能有裸字符串文本块。
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                parts.append(b)
    return "\n".join(parts)


def _has_tool_result(content):
    return any(b.get("type") == "tool_result" for b in _blocks(content))


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _texts(content)
    return "" if content is None else str(content)


def _tool_text(name, args):
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return f'pattern: "{args["pattern"]}"'
    return name


def _usage(msg):
    """assistant message.usage（官方 API 驼峰）→ ATA 蛇形 usage。

    total_tokens 与 cost 在 Claude usage 里没有，写 null。
    """
    raw = (msg or {}).get("usage")
    if not isinstance(raw, dict) or not raw:
        return usage_missing()
    return usage_from_counts(
        int(raw.get("input_tokens") or 0),
        int(raw.get("output_tokens") or 0),
        int(raw.get("cache_read_input_tokens") or 0),
        int(raw.get("cache_creation_input_tokens") or 0),
    )
