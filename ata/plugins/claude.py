"""Claude Code transcript 适配器 (Round 2 收窄版)。

代理主发 message/tool/turn 之后, transcript 退到补录通道: 只负责
session.opened (ai-title) / compaction.boundary / system.api_error 等
账本里别处拿不到的事实。state["turn"] 累加器在 transcript 侧不再 bump
(代理端自管), state dict 仍保留 turn 字段 (后续清理)。
"""
from __future__ import annotations

from datetime import datetime
from ata.plugins.jsonl import translate_file as _jfile
from ata.schema import envelope


def translate_line(raw: dict, state: dict) -> list[dict]:
    typ = raw.get("type")
    session_id = raw.get("sessionId") or state.get("session_id")
    if not session_id:
        return []
    state["session_id"] = session_id
    agent_id = "claude"
    ts = _ts(raw, state)
    state["ts"] = ts
    out = []
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
    if typ == "ai-title":
        title = str(raw.get("aiTitle") or "").strip()
        if title:
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="session.opened",
                payload={"title": title[:80]},
                ts=ts,
                eid=f"{session_id}:opened:title",
            ))
        return out
    if typ == "system":
        _system_line(raw, state, ts, out)
        return out
    # user / assistant 行: 代理主发 message/tool, transcript 不再 emit。
    # 仍返回 out (含 session.opened 兜底), 不调 bump_turn / 不发 turn.started。
    return out


def translate_file(path, offset: int = 0, state: dict | None = None):
    # 无 state 不再用文件名猜 session；JSONL 首条必须携带 sessionId。
    return _jfile(path, translate_line, offset, state)


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
            ts=ts,
            eid=f"{session_id}:compact:{cid}",
        ))
        return out
    if sub == "api_error":
        # 代理端主发 message 后, transcript 这条 api_error 行只发一个 envelope
        # 兜底 (让人工能定位一次失败响应)。代理失败响应不走 translate_capture
        # (没 usage / response_id), 不会冲突。
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
            observed_turn_ordinal=turn,
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

