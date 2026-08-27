from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ata.plugins.common import (
    PLACEHOLDER_MS,
    bump_turn_if_real_user,
    is_context_text,
    tool_end_payload,
    tool_start_payload,
    usage_from_counts,
    usage_missing,
)
from ata.plugins.jsonl import translate_file as _jfile
from ata.schema import envelope


def _emit(state, events):
    """把本行新增事件入 state["_buffer"] 队列, 由 translate_file 收尾按行序统一输出。
    
    走队列而非直接返回 out, 解决 trace 显示异常根因 #2: message.upserted(按 mid
    攒齐后 file 收尾 emit) 与 tool.upserted(行内立即 emit) 的相对顺序错位。
    file 收尾时 translate_file 把队列事件按产生时的 line_seq 升序 emit, 保证
    jsonl 行内的事件相对位置不变(同 mid 内的 message.upserted 在 tool 之前)。
    
    老路径(state["_emit_immediate"]=True): 直接返回 events 供 translate_line 用。
    """
    if not events:
        return
    if state.get("_emit_immediate"):
        # 老路径: 调用方 translate_line 直接拿到 events 当 out 返回
        return events
    buf = state.setdefault("_buffer", [])
    line_seq = state.get("_line_seq", 0)
    for ev in events:
        buf.append((line_seq, ev))


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
    if typ not in {"user", "assistant"}:
        if out:
            emitted = _emit(state, out)
            return emitted or out
        return []
    msg = raw.get("message")
    if isinstance(msg, str):
        content = msg
        role = typ
    elif isinstance(msg, dict):
        content = msg.get("content") or ""
        role = msg.get("role")
    else:
        return out if state.get("_emit_immediate") else (_emit(state, out) or [])
    if role not in {"user", "assistant"}:
        return out if state.get("_emit_immediate") else (_emit(state, out) or [])
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
        if state.get("_emit_immediate"):
            # 老路径: 直接 emit message.upserted, 不走 pending 攒齐。
            out.append(envelope(
                agent_id="claude",
                session_id=session_id,
                type_="message.upserted",
                payload={
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
                turn=state.get("turn") or 1,
                ts=ts,
                eid=f"{session_id}:msg:{mid}",
            ))
        # 按 message_id 攒齐 block: 同 mid 跨多行(同 assistant 含 thinking+text+tool_use
        # 多个 content block 时 jsonl 写成多行)合并为单条 message.upserted。一律攒
        # pending,file 收尾 flush——保证 message.upserted 顺序按 mid 首次出现的
        # jsonl 行序(pending dict 插入序)。tool_use / tool_result 走 out 立即 emit,
        # 它们的双行协议 start/end 事件 id 已拆分,与 message.upserted 排序互不冲突。
        pending = state.setdefault("pending_msg", {})
        prior = pending.pop(mid, None)
        if prior is not None:
            # 同 mid 续行: 合并 texts/thinking, 保留 prior 的 usage/model。
            merged_texts = (prior["texts"] + ("\n" if prior["texts"] and texts else "") + texts)
            merged_thinking = (prior["thinking"] + ("\n" if prior["thinking"] and thinking else "") + thinking)
        else:
            merged_texts = texts
            merged_thinking = thinking
        # 同 mid 多行的 usage/model 只在 API 主行(通常是第一行)有,后续行留空;
        # 这里 prior 的优先,避免被空覆盖。
        is_first = prior is None
        pending[mid] = {
            "role": role,
            "texts": merged_texts,
            "thinking": merged_thinking,
            "usage": (prior.get("usage") if prior else None) or usage,
            "model": (prior.get("model") if prior else None) or model,
            "request_no": state.get("request_no") if role == "assistant" else None,
            "ts": ts,
            "status": (prior.get("status") if prior else None) or "completed",
            "_first_line_seq": (prior.get("_first_line_seq") if prior else None) or state.get("_line_seq", 0),
        }
        # 真正 emit 推迟到 file 收尾的 flush_pending_messages(state)——这样同 mid
        # 跨多行 block 一定合并为单条 message.upserted。
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
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="tool.upserted",
                payload=payload,
                turn=state.get("turn") or 1,
                ts=ts,
                eid=f"{session_id}:tool:{cid}:start",
            ))
        elif block.get("type") == "tool_result":
            cid = str(block.get("tool_use_id") or block.get("id") or "")
            if not cid:
                continue
            result = _result_text(block.get("content"))
            prev = state.setdefault("tools", {}).get(cid, {})
            end_payload = tool_end_payload(prev, cid, state.get("last_assistant_id"), result, ts)
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="tool.upserted",
                payload=end_payload,
                turn=state.get("turn") or 1,
                ts=ts,
                eid=f"{session_id}:tool:{cid}:end",
            ))
    emitted = _emit(state, out)
    if state.get("_emit_immediate"):
        return emitted or out
    return []


def _flush_pending_to_events(pending, session_id, state):
    """把 pending_msg dict 转成 message.upserted 事件列表(纯转, 不入 buffer)。"""
    out = []
    for mid, p in pending.items():
        out.append(envelope(
            agent_id="claude",
            session_id=session_id,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": p["role"],
                "text": (p["texts"] or "")[:200],
                "status": p.get("status") or "completed",
                "request_no": p.get("request_no"),
                "usage": p.get("usage"),
                "started_at": p.get("ts"),
                "duration_ms": PLACEHOLDER_MS,
                "output_text": p["texts"] if p["role"] == "assistant" else None,
                "thinking": p.get("thinking") or None,
                "model": p.get("model"),
            },
            turn=state.get("turn") or 1,
            ts=p.get("ts"),
            eid=f"{session_id}:msg:{mid}",
        ))
    return out


def translate_file(path, offset: int = 0, state: dict | None = None):
    if state is None:
        # 老路径: 每次调用都重建 state 桶,无跨 step 持久。translate_line 返回
        # 的 events 直接累计, message.upserted 在 translate_line 内部就走老逻辑
        # (单行 per translate_file 模式)——为了兼容老测试, 这里回退到不攒齐。
        # 实现: 把 _emit 切到「直接 out 模式」(buffer 不用)。
        state = {"session_id": Path(path).stem, "_emit_immediate": True}
        events, new_offset = _jfile(path, translate_line, offset, state)
        return events, new_offset
    path_key = str(Path(path).resolve())
    # 跨 file 切换: 旧 file 的 buffer + pending 先入 _pre_flush, 再清。
    if state.get("_current_path") and state["_current_path"] != path_key:
        old_sid = state.get("session_id") or Path(state["_current_path"]).stem
        pre = state.setdefault("_pre_flush", [])
        buf_events = [ev for _, ev in state.get("_buffer", [])]
        pending_events = _flush_pending_to_events(
            state.get("pending_msg", {}), old_sid, state)
        pre.extend(buf_events)
        pre.extend(pending_events)
        state["_buffer"] = []
        state["pending_msg"] = {}
        state["_line_seq"] = -1
    state["_current_path"] = path_key
    events, new_offset = _jfile(path, translate_line, offset, state)
    session_id = state.get("session_id") or Path(path).stem
    # 收尾: drain buffer (含 pending 嵌入), 输出按 line_seq 排序
    pre = list(state.get("_pre_flush") or [])
    state["_pre_flush"] = []
    combined = list(state.get("_buffer", []))
    for mid, p in (state.get("pending_msg") or {}).items():
        first_seq = p.get("_first_line_seq")
        if first_seq is None:
            continue
        ev = envelope(
            agent_id="claude",
            session_id=session_id,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": p["role"],
                "text": (p["texts"] or "")[:200],
                "status": p.get("status") or "completed",
                "request_no": p.get("request_no"),
                "usage": p.get("usage"),
                "started_at": p.get("ts"),
                "duration_ms": PLACEHOLDER_MS,
                "output_text": p["texts"] if p["role"] == "assistant" else None,
                "thinking": p.get("thinking") or None,
                "model": p.get("model"),
            },
            turn=state.get("turn") or 1,
            ts=p.get("ts"),
            eid=f"{session_id}:msg:{mid}",
        )
        combined.append((first_seq, ev))
    combined.sort(key=lambda x: x[0])
    out = pre + [ev for _, ev in combined]
    state["_buffer"] = []
    state["pending_msg"] = {}
    state["_line_seq"] = -1
    return out, new_offset


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
        err = raw.get("error") if isinstance(raw.get("error"), dict) else {}
        bits = ["api_error"]
        if err.get("status") is not None:
            bits.append(str(err["status"]))
        attempt, max_r = raw.get("retryAttempt"), raw.get("maxRetries")
        if attempt is not None and max_r is not None:
            bits.append(f"retry {attempt}/{max_r}")
        mid = str(raw.get("uuid") or f"{session_id}:api-error:{turn}:{ts}")
        if state.get("_emit_immediate"):
            # 老路径: 直接 emit message.upserted (failed), 不走 pending。
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
                    "duration_ms": PLACEHOLDER_MS,
                    "output_text": texts,
                    "thinking": None,
                    "model": None,
                },
                turn=turn,
                ts=ts,
                eid=f"{session_id}:msg:{mid}",
            ))
            return out
        # 也走 pending_msg 攒齐, file 收尾 flush——保 message.upserted 事件顺序
        # 按 jsonl 行序, 不让后续 error 抢到正常 user/assistant 行前面。
        pending = state.setdefault("pending_msg", {})
        prior = pending.pop(mid, None)
        texts = " · ".join(bits)
        if prior:
            texts = prior["texts"] + "\n" + texts
        pending[mid] = {
            "role": "assistant",
            "texts": texts,
            "thinking": "",
            "usage": None,
            "model": None,
            "request_no": None,
            "ts": ts,
            "status": "failed",
            "_first_line_seq": state.get("_line_seq", 0),
        }
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
