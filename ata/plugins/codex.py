from __future__ import annotations

from ata.plugins.jsonl import iso_to_ms, translate_file as _jfile


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    session_id = payload.get("session_id") or state.get("session_id") or "codex-session"
    state["session_id"] = session_id
    agent_id = "codex"
    ts = iso_to_ms(raw.get("timestamp"), int(state.get("ts") or 1))
    state["ts"] = ts
    out = []
    if typ == "session_meta":
        if not state.get("opened"):
            state["opened"] = True
            title = str(payload.get("originator") or session_id).strip()[:80] or session_id
            out.append(_ev(
                f"{session_id}:opened", agent_id, session_id, ts,
                "session.opened", None, {"title": title},
            ))
        instructions = payload.get("base_instructions")
        if instructions:
            out.append(_ev(
                f"{session_id}:system:1", agent_id, session_id, ts,
                "system.upserted", None,
                {"prompt_text": str(instructions), "previous_prompt": None, "tools_catalog": []},
            ))
        return out
    if typ == "turn_context":
        model = payload.get("model")
        effort = payload.get("effort")
        if isinstance(model, str) and model:
            state["model"] = model
        if isinstance(effort, str) and effort:
            state["effort"] = effort
        return out
    if typ == "compacted":
        turn = state.get("turn") or 1
        window = payload.get("window_number")
        summary = f"Context compacted · window {window}" if window is not None else "Context compacted"
        out.append(_ev(
            f"{session_id}:compact:{payload.get('window_id') or ts}", agent_id, session_id, ts,
            "compaction.boundary", turn,
            {"summary": summary, "trigger": "compacted"},
        ))
        return out
    if typ == "event_msg":
        return _event_msg(payload, state, ts, out)
    if typ == "response_item":
        return _response_item(payload, state, ts, out)
    # world_state / inter_agent_communication_metadata：跳过
    return out


def translate_file(path, offset: int = 0):
    return _jfile(path, translate_line, offset)


def _ensure_opened(state, ts, out):
    if not state.get("opened"):
        state["opened"] = True
        session_id = state["session_id"]
        out.append(_ev(
            f"{session_id}:opened", "codex", session_id, ts,
            "session.opened", None, {"title": session_id},
        ))
    return out


def _turn_for(state, turn_id, ts, out):
    """turn_id 首次出现分配轮次号并补 turn.started。"""
    if not state.get("opened"):
        _ensure_opened(state, ts, out)
    mapping = state.setdefault("turn_ids", {})
    turn = mapping.get(str(turn_id))
    if turn is None:
        turn = int(state.get("turn") or 0) + 1
        mapping[str(turn_id)] = turn
        state["turn"] = turn
        out.append(_ev(
            f"{state['session_id']}:turn:{turn}:start", "codex", state["session_id"], ts,
            "turn.started", turn, {},
        ))
    return turn


def _event_msg(payload, state, ts, out):
    etype = payload.get("type")
    session_id = state["session_id"]
    if etype == "task_started":
        turn_id = payload.get("turn_id")
        if turn_id is None:
            return out
        _turn_for(state, turn_id, ts, out)
        return out
    if etype == "task_complete":
        turn = state.get("turn") or 1
        usage = state.get("last_token_usage")
        usage = _usage(usage) if usage is not None else None
        out.append(_ev(
            f"{session_id}:turn:{turn}:end", "codex", session_id, ts,
            "turn.ended", turn, {"usage": usage},
        ))
        return out
    if etype == "turn_aborted":
        turn_id = payload.get("turn_id")
        turn = _turn_for(state, turn_id, ts, out) if turn_id is not None else (state.get("turn") or 1)
        out.append(_ev(
            f"{session_id}:turn:{turn}:end:cancelled", "codex", session_id, ts,
            "turn.ended", turn,
            {
                "usage": None,
                "status": "cancelled",
                "note": str(payload.get("reason") or "interrupted"),
            },
        ))
        return out
    if etype == "context_compacted":
        turn = state.get("turn") or 1
        out.append(_ev(
            f"{session_id}:compact:ctx:{ts}", "codex", session_id, ts,
            "compaction.boundary", turn,
            {"summary": "Context compacted", "trigger": "context_compacted"},
        ))
        return out
    if etype == "token_count":
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        last = info.get("last_token_usage")
        if isinstance(last, dict):
            # token_count 每轮会发多次，只保留最近一次，task_complete 时对齐该轮。
            state["last_token_usage"] = last
        return out
    # user_message / agent_message / context_compacted / turn_aborted 等：跳过
    return out


def _response_item(payload, state, ts, out):
    rtype = payload.get("type")
    session_id = state["session_id"]
    if rtype == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return out
        if not state.get("opened"):
            _ensure_opened(state, ts, out)
        if role == "user":
            # 轮次边界由 task_started 显式给出；这里只确保轮次号存在。无 task_started 的旧 rollout 兜底。
            turn = state.get("turn") or 1
            state["turn"] = turn
        else:
            turn = state.get("turn") or 1
            state["turn"] = turn
            state["last_assistant_id"] = str(payload.get("id") or f"{session_id}:asst:{ts}")
            state["request_no"] = int(state.get("request_no") or 0) + 1
        text = _texts(payload.get("content"))
        mid = str(payload.get("id") or f"{session_id}:{role}:{ts}")
        out.append(_ev(
            f"{session_id}:msg:{mid}", "codex", session_id, ts,
            "message.upserted", state.get("turn") or 1,
            {
                "message_id": mid,
                "role": role,
                "text": (text or "")[:200],
                "status": "completed",
                "request_no": state.get("request_no") if role == "assistant" else None,
                "usage": None,
                "started_at": ts,
                "duration_ms": 1,
                "output_text": text if role == "assistant" else None,
                "model": state.get("model") if role == "assistant" else None,
                "effort": state.get("effort") if role == "assistant" else None,
            },
        ))
        return out
    if rtype in {"function_call", "custom_tool_call"}:
        if not state.get("opened"):
            _ensure_opened(state, ts, out)
        cid = str(payload.get("call_id") or "")
        if not cid:
            return out
        name = payload.get("name") or "tool"
        args = _args(payload.get("arguments") if rtype == "function_call" else payload.get("input"))
        pld = {
            "tool_call_id": cid,
            "parent_message_id": state.get("last_assistant_id"),
            "name": name,
            "text": _tool_text(name, args),
            "status": "pending",
            "payload": args,
            "result": None,
            "started_at": ts,
            "duration_ms": None,
        }
        state.setdefault("tools", {})[cid] = pld
        out.append(_ev(
            f"{session_id}:tool:{cid}:start", "codex", session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            pld,
        ))
        return out
    if rtype in {"function_call_output", "custom_tool_call_output"}:
        cid = str(payload.get("call_id") or "")
        if not cid:
            return out
        result = _result_text(payload.get("output"))
        prev = state.setdefault("tools", {}).get(cid, {})
        out.append(_ev(
            f"{session_id}:tool:{cid}:end", "codex", session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            {
                "tool_call_id": cid,
                "parent_message_id": prev.get("parent_message_id") or state.get("last_assistant_id"),
                "name": prev.get("name") or "tool",
                "text": prev.get("text") or (result[:200] if result else cid),
                "status": "completed",
                "payload": prev.get("payload"),
                "result": result,
                "started_at": prev.get("started_at") or ts,
                "duration_ms": 1,
            },
        ))
        return out
    # reasoning / agent_message / web_search_call 等：跳过
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


def _blocks(content):
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def _texts(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in _blocks(content):
        if b.get("text"):
            parts.append(str(b["text"]))
    if isinstance(content, list):
        for b in content:
            if isinstance(b, str):
                parts.append(b)
    return "\n".join(parts)


def _args(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _result_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _texts(content)
    return str(content)


def _tool_text(name, args):
    if "path" in args:
        return str(args["path"])
    if "command" in args:
        return str(args["command"])
    return name


def _usage(last: dict):
    """last_token_usage（TokenUsage）→ ATA usage。全 0 标 missing。"""
    counts = (
        int(last.get("input_tokens") or 0),
        int(last.get("output_tokens") or 0),
        int(last.get("cached_input_tokens") or 0),
        int(last.get("cache_write_input_tokens") or 0),
    )
    if counts == (0, 0, 0, 0):
        return {
            "status": "missing",
            "input": None, "output": None,
            "cache_read": None, "cache_write": None,
            "total_tokens": None, "cost": None,
        }
    return {
        "status": "reported",
        "input": last.get("input_tokens"),
        "output": last.get("output_tokens"),
        "cache_read": last.get("cached_input_tokens"),
        "cache_write": last.get("cache_write_input_tokens"),
        "total_tokens": last.get("total_tokens"),
        "cost": None,
    }
