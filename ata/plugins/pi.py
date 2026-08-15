from __future__ import annotations


ZERO = (0, 0, 0, 0)


def usage_from_assistant(message: dict):
    raw = (message or {}).get("usage") or {}
    stop = (message or {}).get("stopReason")
    counts = (
        int(raw.get("input") or 0),
        int(raw.get("output") or 0),
        int(raw.get("cacheRead") or 0),
        int(raw.get("cacheWrite") or 0),
    )
    if stop in {"error", "aborted"} and counts == ZERO:
        return {
            "status": "missing",
            "input": None,
            "output": None,
            "cache_read": None,
            "cache_write": None,
            "total_tokens": None,
            "cost": None,
        }
    if not raw:
        return None
    return {
        "status": "reported",
        "input": raw.get("input"),
        "output": raw.get("output"),
        "cache_read": raw.get("cacheRead"),
        "cache_write": raw.get("cacheWrite"),
        "total_tokens": raw.get("totalTokens"),
        "cost": (raw.get("cost") or {}).get("total") if isinstance(raw.get("cost"), dict) else raw.get("cost"),
    }


def translate_hook(name, event, ctx, state) -> list[dict]:
    session_id = ctx.get("session_id") or state.get("session_id") or "pi-session"
    state["session_id"] = session_id
    agent_id = "pi"
    ts = int(event.get("timestamp") or state.get("ts") or 1)
    state["ts"] = ts
    out = []
    if name == "agent_start":
        if not state.get("opened"):
            state["opened"] = True
            out.append(_ev(
                f"{session_id}:opened", agent_id, session_id, ts,
                "session.opened", None, {"title": ctx.get("title") or session_id},
            ))
        return out
    if name == "turn_start":
        turn = int(event.get("turnIndex", 0)) + 1
        state["turn"] = turn
        out.append(_ev(
            f"{session_id}:turn:{turn}:start", agent_id, session_id, ts,
            "turn.started", turn, {},
        ))
        return out
    if name in {"message_start", "message_end"}:
        msg = event.get("message") or {}
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            return out
        turn = state.get("turn") or 1
        state["turn"] = turn
        mid = str(msg.get("responseId") or f"{session_id}:{turn}:{role}")
        if role == "assistant":
            state["last_assistant_id"] = mid
        text = _message_text(msg)
        status = "pending" if name == "message_start" else "completed"
        usage = usage_from_assistant(msg) if role == "assistant" and name == "message_end" else None
        req = None
        if role == "assistant":
            if name == "message_end" or not state.get("request_no"):
                state["request_no"] = int(state.get("request_no") or 0) + (1 if name == "message_end" else 0)
            req = state.get("request_no") or 1
            if name == "message_start" and not state.get("request_no"):
                req = int(state.get("seen_asst") or 0) + 1
                state["seen_asst"] = req
        out.append(_ev(
            f"{session_id}:msg:{mid}:{name}", agent_id, session_id, ts,
            "message.upserted", turn,
            {
                "message_id": mid,
                "role": role,
                "text": (text or "")[:200],
                "status": status,
                "request_no": req,
                "usage": usage,
                "started_at": int(msg.get("timestamp") or ts),
                "duration_ms": None if status == "pending" else 1,
                "output_text": text if role == "assistant" else None,
            },
        ))
        return out
    if name == "tool_execution_start":
        cid = str(event.get("toolCallId") or "")
        if not cid:
            return out
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        out.append(_ev(
            f"{session_id}:tool:{cid}", agent_id, session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            {
                "tool_call_id": cid,
                "parent_message_id": state.get("last_assistant_id"),
                "name": event.get("toolName") or "tool",
                "text": str(args.get("path") or event.get("toolName") or cid),
                "status": "pending",
                "payload": args,
                "result": None,
                "started_at": ts,
                "duration_ms": None,
            },
        ))
        return out
    if name == "tool_execution_end":
        cid = str(event.get("toolCallId") or "")
        if not cid:
            return out
        result = _tool_result(event.get("result"))
        out.append(_ev(
            f"{session_id}:tool:{cid}", agent_id, session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            {
                "tool_call_id": cid,
                "parent_message_id": state.get("last_assistant_id"),
                "name": event.get("toolName") or "tool",
                "text": result[:200] if result else cid,
                "status": "failed" if event.get("isError") else "completed",
                "payload": event.get("args") if isinstance(event.get("args"), dict) else None,
                "result": result,
                "started_at": ts,
                "duration_ms": 1,
            },
        ))
        return out
    if name == "turn_end":
        turn = int(event.get("turnIndex", (state.get("turn") or 1) - 1)) + 1
        state["turn"] = turn
        msg = event.get("message") or {}
        usage = usage_from_assistant(msg)
        if msg.get("role") == "assistant":
            mid = str(msg.get("responseId") or state.get("last_assistant_id") or f"{session_id}:{turn}:assistant")
            state["last_assistant_id"] = mid
            text = _message_text(msg)
            out.append(_ev(
                f"{session_id}:msg:{mid}:end", agent_id, session_id, ts,
                "message.upserted", turn,
                {
                    "message_id": mid,
                    "role": "assistant",
                    "text": (text or "")[:200],
                    "status": "completed",
                    "request_no": state.get("request_no") or 1,
                    "usage": usage,
                    "started_at": int(msg.get("timestamp") or ts),
                    "duration_ms": 1,
                    "output_text": text,
                },
            ))
        out.append(_ev(
            f"{session_id}:turn:{turn}:end", agent_id, session_id, ts,
            "turn.ended", turn, {"usage": usage},
        ))
        return out
    if name == "agent_end":
        out.append(_ev(
            f"{session_id}:closed", agent_id, session_id, ts,
            "session.closed", None, {},
        ))
    return out


def _ev(eid, agent_id, session_id, ts, typ, turn, payload):
    return {
        "v": 1,
        "id": eid,
        "agent_id": agent_id,
        "session_id": session_id,
        "ts": int(ts),
        "type": typ,
        "turn": turn,
        "payload": payload,
    }


def _message_text(msg):
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _tool_result(result):
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return _message_text({"content": content})
    return str(result)
