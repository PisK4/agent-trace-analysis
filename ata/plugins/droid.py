from __future__ import annotations

from pathlib import Path


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    session_id = raw.get("sessionId") or state.get("session_id") or "droid-session"
    state["session_id"] = session_id
    agent_id = "droid"
    out = []
    if typ == "session_start":
        if not state.get("opened"):
            state["opened"] = True
            out.append(_ev(
                f"{session_id}:opened", agent_id, session_id, raw.get("ts") or 1,
                "session.opened", None, {"title": session_id},
            ))
        return out
    if typ in {"todo_state", "compaction_state"} or typ not in {"message", "agent_turn_outcome"}:
        return out
    if not state.get("opened"):
        state["opened"] = True
        out.append(_ev(
            f"{session_id}:opened", agent_id, session_id, raw.get("ts") or 1,
            "session.opened", None, {"title": session_id},
        ))
    if typ == "agent_turn_outcome":
        turn = state.get("turn") or 1
        out.append(_ev(
            f"{session_id}:turn:{turn}:end", agent_id, session_id, raw.get("ts") or 1,
            "turn.ended", turn, {"usage": None},
        ))
        return out
    role = raw.get("role")
    content = raw.get("content")
    ts = int(raw.get("ts") or raw.get("timestamp") or 1)
    if role in {"user", "assistant"}:
        texts = _texts(content)
        is_tool_only = role == "user" and texts == "" and _has_tool_result(content)
        if not is_tool_only:
            if role == "user":
                state["turn"] = int(state.get("turn") or 0) + 1
                turn = state["turn"]
                if turn not in state.setdefault("started_turns", set()):
                    state["started_turns"].add(turn)
                    out.append(_ev(
                        f"{session_id}:turn:{turn}:start", agent_id, session_id, ts,
                        "turn.started", turn, {},
                    ))
            else:
                turn = state.get("turn") or 1
                state["turn"] = turn
            mid = str(raw.get("id") or f"{session_id}:{role}:{ts}")
            if role == "assistant":
                state["last_assistant_id"] = mid
                state["request_no"] = int(state.get("request_no") or 0) + 1
            text = texts or ""
            out.append(_ev(
                f"{session_id}:msg:{mid}", agent_id, session_id, ts,
                "message.upserted", turn,
                {
                    "message_id": mid,
                    "role": role,
                    "text": text[:200],
                    "status": "completed",
                    "request_no": state.get("request_no") if role == "assistant" else None,
                    "usage": None,
                    "started_at": ts,
                    "duration_ms": 1,
                    "output_text": text if role == "assistant" else None,
                },
            ))
        else:
            turn = state.get("turn") or 1
        for block in _blocks(content):
            if block.get("type") == "tool_use":
                cid = str(block.get("id") or "")
                if not cid:
                    continue
                name = block.get("name") or "tool"
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                payload = {
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
                state.setdefault("tools", {})[cid] = payload
                # 与 Pi 插件同款修法（见 plugins/pi.py）：start/end 拆成两个 event id，
                # 否则幂等账本（重复 id 只认第一条）会吞掉 tool_result 的完成态，
                # 工具行永远 pending。投影层按 tool_call_id 合并，后写覆盖前写。
                out.append(_ev(
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
                out.append(_ev(
                    f"{session_id}:tool:{cid}:end", agent_id, session_id, ts,
                    "tool.upserted", state.get("turn") or 1,
                    {
                        "tool_call_id": cid,
                        "parent_message_id": prev.get("parent_message_id") or state.get("last_assistant_id"),
                        "name": block.get("name") or prev.get("name") or "tool",
                        "text": prev.get("text") or (result[:200] if result else cid),
                        "status": "completed",
                        "payload": prev.get("payload"),
                        "result": result,
                        "started_at": prev.get("started_at") or ts,
                        "duration_ms": 1,
                    },
                ))
    return out


def translate_file(path: Path, offset: int = 0):
    # 增量 JSONL 读取/半行容错/坏行跳过统一在 plugins/jsonl.py（与 claude/codex 共用）。
    from ata.plugins.jsonl import translate_file as _jfile
    return _jfile(path, translate_line, offset)


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
    for block in _blocks(content):
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
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
