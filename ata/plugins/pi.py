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
    agent_id = ctx.get("agent_id") or state.get("agent_id") or "pi"
    state["agent_id"] = agent_id
    identity = {
        key: ctx[key]
        for key in ("host", "runtime")
        if isinstance(ctx.get(key), str) and ctx[key]
    }
    ts = int(event.get("timestamp") or state.get("ts") or 1)
    state["ts"] = ts
    out = []
    if name == "before_agent_start":
        # Pi 契约（锚定 845d6ff1）：systemPrompt + systemPromptOptions
        # （selectedTools 只是名字数组，toolSnippets 是 {name: 单行描述}）。
        prompt = event.get("systemPrompt") or ""
        if not prompt:
            return out
        opts = event.get("systemPromptOptions")
        snippets = opts.get("toolSnippets") if isinstance(opts, dict) and isinstance(opts.get("toolSnippets"), dict) else {}
        catalog = [
            {"name": str(n), "description": (str(s) or "")[:200], "parameters": {}}
            for n, s in snippets.items()
        ]
        n = int(state.get("sys_no") or 0) + 1
        state["sys_no"] = n
        out.append(_ev(
            f"{session_id}:system:{n}", agent_id, session_id, ts,
            "system.upserted", None,
            {
                "prompt_text": prompt,
                "previous_prompt": state.get("last_prompt"),
                "tools_catalog": catalog,
            },
        ))
        state["last_prompt"] = prompt
        return out
    if name == "agent_start":
        if not state.get("opened"):
            state["opened"] = True
            title = ctx.get("title") or session_id
            state["title_set"] = title != session_id
            out.append(_ev(
                f"{session_id}:opened", agent_id, session_id, ts,
                "session.opened", None, {"title": title, **identity},
            ))
        return out
    if name == "turn_start":
        # Pi 的 turnIndex 每个 agent run 都从 0 起算（自动重试/压缩后也会重来），
        # 真正的轮次边界是用户消息：轮次号在用户消息到达时递增。
        state["last_assistant_id"] = None
        return out
    if name in {"message_start", "message_end"}:
        msg = event.get("message") or {}
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            return out
        if role == "user":
            is_new = name == "message_start" or not state.get("user_pending")
            if is_new:
                state["turn"] = int(state.get("turn") or 0) + 1
                state["last_assistant_id"] = None
                if int(state.get("turn_started") or 0) < state["turn"]:
                    state["turn_started"] = state["turn"]
                    out.append(_ev(
                        f"{session_id}:turn:{state['turn']}:start", agent_id, session_id, ts,
                        "turn.started", state["turn"], {},
                    ))
                # Pi 未显式命名会话时（getSessionName 未设置），标题取第一条用户消息。
                if not state.get("title_set") and (ctx.get("title") or "") in {"", session_id}:
                    first = _message_text(msg)
                    if first:
                        state["title_set"] = True
                        out.append(_ev(
                            f"{session_id}:opened:title", agent_id, session_id, ts,
                            "session.opened", None, {"title": first[:80]},
                        ))
            state["user_pending"] = name == "message_start"
            turn = state["turn"]
            mid = f"{session_id}:{turn}:user"
            req = None
        else:
            turn = int(state.get("turn") or 0) or 1
            state["turn"] = turn
            if name == "message_start":
                mid = str(msg.get("responseId") or f"{session_id}:asst:{int(state.get('asst_no') or 0) + 1}")
                if not msg.get("responseId"):
                    state["asst_no"] = int(state.get("asst_no") or 0) + 1
                state["last_assistant_id"] = mid
                state["request_no"] = int(state.get("request_no") or 0) + 1
                state.setdefault("msg_start_ts", {})[mid] = ts
            else:
                # 流式开始时可能还没有 responseId：message_start 定下的 id 就是
                # 本条消息的规范 id，message_end / turn_end 复用，避免幽灵行。
                mid = str(
                    state.get("last_assistant_id")
                    or msg.get("responseId")
                    or f"{session_id}:asst:{int(state.get('asst_no') or 0) + 1}"
                )
                if not state.get("last_assistant_id"):
                    state["asst_no"] = int(state.get("asst_no") or 0) + 1
                    state["last_assistant_id"] = mid
            req = state.get("request_no") or 1
        text = _message_text(msg)
        status = "pending" if name == "message_start" else "completed"
        usage = usage_from_assistant(msg) if role == "assistant" and name == "message_end" else None
        # assistant end 行用真实毫秒差；user 行 Pi 未提供耗时，维持占位。
        duration = None if status == "pending" else 1
        if role == "assistant" and name == "message_end":
            m_start = state.get("msg_start_ts", {}).get(mid)
            duration = max(int(ts) - int(m_start), 0) if m_start else 0
            state.setdefault("msg_dur", {})[mid] = duration
        out.append(_ev(
            f"{session_id}:msg:{mid}:{name}", agent_id, session_id, ts,
            "message.upserted", turn,
            {
                "message_id": mid,
                "role": role,
                "text": text or "",
                "status": status,
                "request_no": req,
                "usage": usage,
                "started_at": int(msg.get("timestamp") or ts),
                "duration_ms": duration,
                "output_text": text if role == "assistant" else None,
            },
        ))
        return out
    if name == "tool_execution_start":
        cid = str(event.get("toolCallId") or "")
        if not cid:
            return out
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        state.setdefault("tool_args", {})[cid] = args
        state.setdefault("tool_start_ts", {})[cid] = ts
        out.append(_ev(
            f"{session_id}:tool:{cid}:start", agent_id, session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            {
                "tool_call_id": cid,
                "parent_message_id": state.get("last_assistant_id"),
                "name": event.get("toolName") or "tool",
                "text": _tool_text(args),
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
        # ToolExecutionEndEvent 不带 args（锚定 845d6ff1），从 start 存的状态取回。
        args = state.get("tool_args", {}).get(cid) or {}
        result = _tool_result(event.get("result"))
        start_ts = state.get("tool_start_ts", {}).pop(cid, None)
        duration = max(int(ts) - int(start_ts), 0) if start_ts else 0
        out.append(_ev(
            f"{session_id}:tool:{cid}:end", agent_id, session_id, ts,
            "tool.upserted", state.get("turn") or 1,
            {
                "tool_call_id": cid,
                "parent_message_id": state.get("last_assistant_id"),
                "name": event.get("toolName") or "tool",
                "text": _tool_text(args),
                "status": "failed" if event.get("isError") else "completed",
                "payload": args,
                "result": result,
                "started_at": ts,
                "duration_ms": duration,
            },
        ))
        return out
    if name == "turn_end":
        turn = int(state.get("turn") or 0) or 1
        state["turn"] = turn
        msg = event.get("message") or {}
        usage = usage_from_assistant(msg)
        if msg.get("role") == "assistant":
            text = _message_text(msg)
            # 空文本（turn_end 的消息常不带 content 块）不重发 upsert，
            # 否则会用空文本覆盖 message_end 已落定的行；usage 走 turn.ended 回填。
            if text:
                mid = str(
                    state.get("last_assistant_id")
                    or msg.get("responseId")
                    or f"{session_id}:asst:{int(state.get('asst_no') or 0) + 1}"
                )
                if not state.get("last_assistant_id"):
                    state["asst_no"] = int(state.get("asst_no") or 0) + 1
                    state["last_assistant_id"] = mid
                out.append(_ev(
                    f"{session_id}:msg:{mid}:end", agent_id, session_id, ts,
                    "message.upserted", turn,
                    {
                        "message_id": mid,
                        "role": "assistant",
                        "text": text or "",
                        "status": "completed",
                        "request_no": state.get("request_no") or 1,
                        "usage": usage,
                        "started_at": int(msg.get("timestamp") or ts),
                        "duration_ms": state.get("msg_dur", {}).get(mid),
                        "output_text": text,
                    },
                ))
        out.append(_ev(
            f"{session_id}:turn:{turn}:end", agent_id, session_id, ts,
            "turn.ended", turn, {"usage": usage},
        ))
        return out
    # agent_end / agent_settled / 其他：不做收尾。以前把 agent_end 当会话结束，
    # 会在自动重试/续跑的下一次 agent run 之前提前关闭会话。
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
            if isinstance(block, dict):
                if block.get("type") == "thinking" and block.get("thinking"):
                    parts.append(str(block["thinking"]))
                elif block.get("text"):
                    parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _tool_text(args):
    for key in ("path", "command"):
        v = args.get(key)
        if v:
            return str(v)
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
