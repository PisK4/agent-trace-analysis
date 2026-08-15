from __future__ import annotations

import json
import time
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
            text = texts or "(empty)"
            out.append(_ev(
                f"{session_id}:msg:{mid}", agent_id, session_id, ts,
                "message.upserted", turn,
                {
                    "message_id": mid,
                    "role": role,
                    "text": text[:200],
                    "status": "completed",
                    "request_no": None if role == "user" else int(state.get("request_no", 0)) + (1 if role == "assistant" else 0) or None,
                    "usage": None,
                    "started_at": ts,
                    "duration_ms": 1,
                    "output_text": text if role == "assistant" else None,
                },
            ))
            if role == "assistant":
                state["request_no"] = int(state.get("request_no") or 0) + 1
                out[-1]["payload"]["request_no"] = state["request_no"]
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
                out.append(_ev(
                    f"{session_id}:tool:{cid}", agent_id, session_id, ts,
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
                    f"{session_id}:tool:{cid}", agent_id, session_id, ts,
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
    data = Path(path).read_bytes()
    chunk = data[offset:]
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n") and b"\n" in chunk:
        keep = text.rfind("\n") + 1
        rest = text[:keep]
        new_offset = offset + len(rest.encode("utf-8"))
    else:
        rest = text
        new_offset = offset + len(chunk)
    state = {"session_id": Path(path).stem}
    events = []
    for line in rest.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        events.extend(translate_line(raw, state))
    return events, new_offset


def tail_forever(path: Path, ledger):
    from ata.schema import parse_event
    offset = 0
    while True:
        events, offset = translate_file(path, offset)
        for ev in events:
            ledger.append(parse_event(ev))
        time.sleep(1)


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
