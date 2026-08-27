"""Claude Code transcript 适配器 (Round 2 收窄版)。

代理主发 message/tool/turn 之后, transcript 退到补录通道: 只负责
session.opened (ai-title) / compaction.boundary / system.api_error 等
账本里别处拿不到的事实。

历史: fb74ff2 落 state 跨 step 持久 + pending 攒齐是为 jsonl 通道自管
message 而设计, Round 2 之后 message/tool 走代理, jsonl 不再需要 pending
攒齐 — 但 pending / _buffer 基础设施保留 (兼容老 _emit_immediate 路径的
测试)。state["turn"] 累加器在 transcript 侧不再 bump (代理端自管),
state dict 仍保留 turn 字段 (后续清理)。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ata.plugins.jsonl import translate_file as _jfile
from ata.schema import envelope


def _emit(state, events):
    """新路径 (Round 2 起): events 直接返回 (无 buffer, 无 line_seq 排序, 无
    pending)。老路径 (state["_emit_immediate"]=True) 仍走 buffer 模式以保留
    第 1 轮 (state 跨 step 持久) 的测试基线。
    """
    if not events:
        return
    if state.get("_emit_immediate"):
        return events
    return events


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    session_id = raw.get("sessionId") or state.get("session_id") or "claude-session"
    state["session_id"] = session_id
    agent_id = "claude"
    ts = _ts(raw, state)
    state["ts"] = ts
    state["_line_seq"] = state.get("_line_seq", -1) + 1
    out = []
    if not state.get("opened"):
        state["opened"] = True
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="session.opened",
            payload={"title": session_id},
            turn=None,
            ts=ts,
            eid=f"{session_id}:opened",
        ))
    if typ == "ai-title":
        title = str(raw.get("aiTitle") or "").strip()
        if title:
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="session.opened",
                payload={"title": title[:80]},
                turn=None,
                ts=ts,
                eid=f"{session_id}:opened:title",
            ))
        emitted = _emit(state, out)
        return emitted or out
    if typ == "system":
        _system_line(raw, state, ts, out)
        emitted = _emit(state, out)
        return emitted or out
    # user / assistant 行: 代理主发 message/tool, transcript 不再 emit。
    # 仍返回 out (含 session.opened 兜底), 不调 bump_turn / 不发 turn.started。
    if out:
        emitted = _emit(state, out)
        return emitted or out
    return []


def translate_file(path, offset: int = 0, state: dict | None = None):
    if state is None:
        # 老路径: 每次调用都重建 state 桶, 无跨 step 持久。translate_line 返回
        # 的 events 直接累计, 走 _emit_immediate 兼容老测试。
        state = {"session_id": Path(path).stem, "_emit_immediate": True}
        events, new_offset = _jfile(path, translate_line, offset, state)
        return events, new_offset
    events, new_offset = _jfile(path, translate_line, offset, state)
    return events, new_offset


def _system_line(raw, state, ts, out):
    sub = raw.get("subtype")
    session_id = state["session_id"]
    turn = state.get("turn") or 1
    state["turn"] = turn
    if sub == "compact_boundary":
        meta = raw.get("compactMetadata") if isinstance(raw.get("compactMetadata"), dict) else {}
        cid = str(raw.get("uuid") or ts)
        out.append(envelope(
            agent_id="claude",
            session_id=session_id,
            type_="compaction.boundary",
            payload={
                "summary": "Context compacted",
                "trigger": meta.get("trigger"),
                "pre_tokens": meta.get("preTokens"),
                "post_tokens": meta.get("postTokens"),
                "duration_ms": meta.get("durationMs"),
            },
            turn=turn,
            ts=ts,
            eid=f"{session_id}:compact:{cid}",
        ))
        return out
    if sub == "api_error":
        # Round 2 收窄后: 代理端已主发 message/tool, transcript 这条 api_error
        # 行也只发一个 envelope 兜底(让人工能定位一次失败响应),不再写
        # message.upserted / pending。文本是错误摘要。
        err = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        bits = ["api_error"]
        if err.get("status") is not None:
            bits.append(str(err["status"]))
        attempt, max_r = raw.get("retryAttempt"), raw.get("maxRetries")
        if attempt is not None and max_r is not None:
            bits.append(f"retry {attempt}/{max_r}")
        mid = str(raw.get("uuid") or f"{session_id}:api-error:{turn}:{ts}")
        texts = " · ".join(bits)
        out.append(envelope(
            agent_id="claude",
            session_id=session_id,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": "assistant",
                "text": texts[:200],
                "status": "failed",
                "request_no": None,
                "usage": None,
                "started_at": ts,
                "duration_ms": 1,
                "output_text": texts,
                "thinking": None,
                "model": None,
            },
            turn=turn,
            ts=ts,
            eid=f"{session_id}:msg:{mid}",
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
