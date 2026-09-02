from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ata.plugins.common import (
    PLACEHOLDER_MS,
    block_texts,
    bump_turn_if_real_user,
    content_blocks,
    is_context_text,
    result_text,
    split_text_thinking,
    tool_end_payload,
    tool_start_payload,
)
from ata.schema import envelope


def refresh_titles(root: Path, ledger, state: dict | None = None) -> None:
    # Droid 会话开始时 title 是字面 "New Session"，首条消息后才自动生成并原地重写
    # 第一行；按字节偏移 tail 不会再读到第一行，账本里的旧标题永远得不到纠正。
    # 修正以追加 opened 事件落进事件流：详情页标题是从事件流投影的（后写覆盖），
    # 只 UPDATE sessions 表会出现列表已纠正、点开又变回 New Session 的割裂。
    # state: {session_id: (mtime_ns, size)}，调用方持久持有。文件签名没变就只
    # stat 不读，稳态开销趋近于零；签名变了（含之后的再次改名）就重读首行，
    # 修正事件 id 按标题定哈希，重复追加被账本按 id 幂等吸收。
    root = Path(root)
    state = {} if state is None else state
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else [root] if root.is_file() else []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        sig = (st.st_mtime_ns, st.st_size)
        if state.get(f.stem) == sig:
            continue
        state[f.stem] = sig
        try:
            with open(f, "rb") as fh:
                raw = json.loads(fh.readline())
        except (OSError, ValueError):
            continue
        if raw.get("type") != "session_start":
            continue
        title = str(raw.get("title") or "").strip()
        if not title or title == "New Session":
            continue
        # 只纠账本里已有的会话：不为 tail 窗口（默认 7 天）外的历史文件凭空建空壳。
        try:
            cur = ledger.session(f.stem)
        except Exception:
            continue
        if cur is None:
            continue
        sid = f.stem
        digest = hashlib.sha1(title.encode()).hexdigest()[:12]
        ledger.append(envelope(
            "droid", sid, "session.opened", {"title": title},
            ts=int(time.time() * 1000), eid=f"{sid}:title-fix:{digest}"))


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    # v2 形状（2026-08-16 审计 ~/.factory/sessions）：session_id 在 session_start 的
    # `id` 字段，且带 `title`；v1 形状（marketplace 描述）用顶层 `sessionId`。
    # 注意 `id` 只从 session_start 取——message 行的 `id` 是消息 id，会污染 session_id。
    if typ == "session_start":
        session_id = raw.get("sessionId") or raw.get("id") or state.get("session_id")
    else:
        session_id = raw.get("sessionId") or state.get("session_id")
    if not session_id:
        return []
    state["session_id"] = session_id
    agent_id = "droid"
    # droid v2 的 timestamp 是 ISO 字符串（如 2026-07-21T04:33:47.111Z），统一转毫秒。
    from ata.plugins.jsonl import iso_to_ms
    ts = iso_to_ms(raw.get("ts") or raw.get("timestamp"), int(state.get("ts") or 1))
    state["ts"] = ts
    out = []
    if typ == "session_start":
        if not state.get("opened"):
            state["opened"] = True
            title = str(raw.get("title") or session_id).strip()[:80] or session_id
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="session.opened",
                payload={"title": title},
                ts=ts,
                eid=f"{session_id}:opened",
            ))
        return out
    if typ == "todo_state" or typ not in {"message", "agent_turn_outcome", "compaction_state"}:
        return out
    if not state.get("opened"):
        state["opened"] = True
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="session.opened",
            payload={"title": session_id},
            ts=ts,
            eid=f"{session_id}:opened",
        ))
    if typ == "compaction_state":
        turn = state.get("turn") or 1
        kind = raw.get("summaryKind") or "compaction"
        summary = str(raw.get("summaryText") or "").strip()
        if not summary:
            summary = "Provider switch serialization" if kind == "provider_switch_serialization" else "Context compacted"
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="compaction.boundary",
            payload={
                "summary": summary[:200],
                "trigger": kind,
                "removed_count": raw.get("removedCount"),
                "raw": summary[:2000] if raw.get("summaryText") else None,
            },
            ts=ts,
            eid=f"{session_id}:compact:{raw.get('id') or ts}",
        ))
        return out
    if typ == "agent_turn_outcome":
        turn = state.get("turn") or 1
        reason = str(raw.get("reason") or "")
        status = "cancelled" if reason == "cancelled" else "failed" if reason == "error" else None
        payload = {"usage": None}
        if status:
            payload["status"] = status
        eid = f"{session_id}:turn:{turn}:end"
        if status:
            eid = f"{eid}:{status}"
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="turn.ended",
            payload=payload,
            observed_turn_ordinal=turn,
            ts=ts,
            eid=eid,
        ))
        return out
    # v2：消息嵌套在 `message` 字段（{role, content, visibility}）；v1 顶层 role/content 兼容。
    msg = raw.get("message")
    if isinstance(msg, dict):
        role = msg.get("role") or raw.get("role")
        content = msg.get("content")
    else:
        role = raw.get("role")
        content = raw.get("content")
    # Droid 把 hook 执行记录也写成 role=user 的 message 行（content 为空、带
    # hookEventName/hookResults 等字段），不是对话轮次；入库会变成空白 USER 行。
    if isinstance(msg, dict) and msg.get("hookEventName"):
        return out
    if role in {"user", "assistant"}:
        texts, thinking = split_text_thinking(content)
        is_tool_only = role == "user" and texts == "" and _has_tool_result(content)
        if not is_tool_only:
            if role == "user" and not is_context_text(texts):
                bump_turn_if_real_user(state, texts, agent_id, session_id, ts,
                                       lambda e: out.append(e))
                turn = state.get("turn") or 1
            else:
                turn = state.get("turn") or 1
                state["turn"] = turn
            mid = str(raw.get("id") or f"{session_id}:{role}:{ts}")
            if role == "assistant":
                state["last_assistant_id"] = mid
                state["request_no"] = int(state.get("request_no") or 0) + 1
            text = texts or ""
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="message.upserted",
                payload={
                    "message_id": mid,
                    "role": role,
                    "text": text[:200],
                    "status": "completed",
                    "request_no": state.get("request_no") if role == "assistant" else None,
                    "usage": None,
                    "started_at": ts,
                    "duration_ms": PLACEHOLDER_MS,
                    "output_text": text if role == "assistant" else None,
                    "thinking": thinking or None,
                },
                observed_turn_ordinal=turn,
                ts=ts,
                eid=f"{session_id}:msg:{mid}",
            ))
        else:
            turn = state.get("turn") or 1
        for block in content_blocks(content):
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
                # 与 Pi 插件同款修法（见 plugins/pi.py）：start/end 拆成两个 event id，
                # 否则幂等账本（重复 id 只认第一条）会吞掉 tool_result 的完成态，
                # 工具行永远 pending。投影层按 tool_call_id 合并，后写覆盖前写。
                out.append(envelope(
                    agent_id=agent_id,
                    session_id=session_id,
                    type_="tool.upserted",
                    payload=payload,
                    observed_turn_ordinal=state.get("turn") or 1,
                    ts=ts,
                    eid=f"{session_id}:tool:{cid}:start",
                ))
            elif block.get("type") == "tool_result":
                cid = str(block.get("tool_use_id") or block.get("id") or "")
                if not cid:
                    continue
                result = result_text(block.get("content"))
                prev = state.setdefault("tools", {}).get(cid, {})
                end_payload = tool_end_payload(prev, cid, state.get("last_assistant_id"), result, ts)
                out.append(envelope(
                    agent_id=agent_id,
                    session_id=session_id,
                    type_="tool.upserted",
                    payload=end_payload,
                    observed_turn_ordinal=state.get("turn") or 1,
                    ts=ts,
                    eid=f"{session_id}:tool:{cid}:end",
                ))
    return out


def translate_file(path: Path, offset: int = 0, state: dict | None = None):
    # 增量 JSONL 读取/半行容错/坏行跳过统一在 plugins/jsonl.py（与 claude/codex 共用）。
    from ata.plugins.jsonl import translate_file as _jfile
    return _jfile(path, translate_line, offset, state)


def _has_tool_result(content):
    return any(b.get("type") == "tool_result" for b in content_blocks(content))


def _tool_text(name, args):
    if "path" in args:
        return str(args["path"])
    if "pattern" in args:
        return f'pattern: "{args["pattern"]}"'
    return name
