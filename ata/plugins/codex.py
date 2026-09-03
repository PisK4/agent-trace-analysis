from __future__ import annotations

from ata.plugins.common import (
    PLACEHOLDER_MS,
    block_texts,
    result_text,
    tool_end_payload,
    tool_start_payload,
    usage_from_counts,
)
from ata.plugins.jsonl import iso_to_ms, translate_file as _jfile
from ata.schema import envelope


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    session_id = payload.get("session_id") or state.get("session_id")
    if not session_id:
        return []
    state["session_id"] = session_id
    agent_id = "codex"
    ts = iso_to_ms(raw.get("timestamp"), int(state.get("ts") or 1))
    state["ts"] = ts
    out = []
    if typ == "session_meta":
        if not state.get("opened"):
            state["opened"] = True
            title = str(payload.get("originator") or session_id).strip()[:80] or session_id
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="session.opened",
                payload={"title": title},
                ts=ts,
                eid=f"{session_id}:opened",
            ))
        instructions = payload.get("base_instructions")
        if instructions:
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="system.upserted",
                payload={"prompt_text": str(instructions), "previous_prompt": None, "tools_catalog": []},
                ts=ts,
                eid=f"{session_id}:system:1",
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
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="compaction.boundary",
            payload={"summary": summary, "trigger": "compacted"},
            ts=ts,
            eid=f"{session_id}:compact:{payload.get('window_id') or ts}",
        ))
        return out
    if typ == "event_msg":
        return _event_msg(payload, state, ts, out)
    if typ == "response_item":
        return _response_item(payload, state, ts, out)
    # world_state / inter_agent_communication_metadata：跳过
    return out


def translate_file(path, offset: int = 0, state: dict | None = None):
    # 无 state 不再按文件名猜 session；生产 tail 透传持久翻译状态。
    return _jfile(path, translate_line, offset, state)


def _ensure_opened(state, ts, out):
    if not state.get("opened"):
        state["opened"] = True
        session_id = state["session_id"]
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="session.opened",
            payload={"title": session_id},
            ts=ts,
            eid=f"{session_id}:opened",
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
        out.append(envelope(
            agent_id="codex",
            session_id=state["session_id"],
            type_="turn.started",
            payload={},
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{state['session_id']}:turn:{turn}:start",
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
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="turn.ended",
            payload={"usage": usage},
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{session_id}:turn:{turn}:end",
        ))
        return out
    if etype == "turn_aborted":
        turn_id = payload.get("turn_id")
        turn = _turn_for(state, turn_id, ts, out) if turn_id is not None else (state.get("turn") or 1)
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="turn.ended",
            payload={
                "usage": None,
                "status": "cancelled",
                "note": str(payload.get("reason") or "interrupted"),
            },
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{session_id}:turn:{turn}:end:cancelled",
        ))
        return out
    if etype == "context_compacted":
        turn = state.get("turn") or 1
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="compaction.boundary",
            payload={"summary": "Context compacted", "trigger": "context_compacted"},
            ts=ts,
            eid=f"{session_id}:compact:ctx:{ts}",
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
        text = block_texts(payload.get("content"), raw_strings=True)
        mid = str(payload.get("id") or f"{session_id}:{role}:{ts}")
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": role,
                "text": (text or "")[:200],
                "status": "completed",
                "request_no": state.get("request_no") if role == "assistant" else None,
                "usage": None,
                "started_at": ts,
                "duration_ms": PLACEHOLDER_MS,
                "output_text": text if role == "assistant" else None,
                "model": state.get("model") if role == "assistant" else None,
                "effort": state.get("effort") if role == "assistant" else None,
            },
            observed_turn_ordinal=state.get("turn") or 1,
            ts=ts,
            eid=f"{session_id}:msg:{mid}",
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
        pld = tool_start_payload(
            cid, state.get("last_assistant_id"), name, args,
            _tool_text(name, args), ts)
        state.setdefault("tools", {})[cid] = pld
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="tool.upserted",
            payload=pld,
            observed_turn_ordinal=state.get("turn") or 1,
            ts=ts,
            eid=f"{session_id}:tool:{cid}:start",
        ))
        return out
    if rtype in {"function_call_output", "custom_tool_call_output"}:
        cid = str(payload.get("call_id") or "")
        if not cid:
            return out
        result = result_text(payload.get("output"))
        prev = state.setdefault("tools", {}).get(cid, {})
        end_payload = tool_end_payload(prev, cid, state.get("last_assistant_id"), result, ts)
        out.append(envelope(
            agent_id="codex",
            session_id=session_id,
            type_="tool.upserted",
            payload=end_payload,
            observed_turn_ordinal=state.get("turn") or 1,
            ts=ts,
            eid=f"{session_id}:tool:{cid}:end",
        ))
        return out
    # reasoning / agent_message / web_search_call 等：跳过
    return out


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


def _tool_text(name, args):
    if "path" in args:
        return str(args["path"])
    if "command" in args:
        return str(args["command"])
    return name


def _usage(last: dict):
    """last_token_usage（TokenUsage）→ ATA usage。「全 0 计 missing」判定在 common。"""
    return usage_from_counts(
        int(last.get("input_tokens") or 0),
        int(last.get("output_tokens") or 0),
        int(last.get("cached_input_tokens") or 0),
        int(last.get("cache_write_input_tokens") or 0),
        total_tokens=last.get("total_tokens"),
    )
