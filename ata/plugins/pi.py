from __future__ import annotations

import hashlib
import json

from ata.plugins.common import usage_missing
from ata.schema import envelope


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
        return usage_missing()
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
        # Pi 契约：systemPrompt + systemPromptOptions（toolSnippets 是
        # {name: 单行描述}）；skills 与 toolsFull 见 b1efcf7 / v0.84.2。
        prompt = event.get("systemPrompt") or ""
        if not prompt:
            return out
        opts = event.get("systemPromptOptions")
        snippets = opts.get("toolSnippets") if isinstance(opts, dict) and isinstance(opts.get("toolSnippets"), dict) else {}
        catalog = [
            {"name": str(n), "description": (str(s) or "")[:200], "parameters": {}}
            for n, s in snippets.items()
        ]
        # toolSnippets 无参数 schema；extension 在事件上附带 getAllTools 快照，
        # 按名字回填 parameters。
        full = event.get("toolsFull")
        schemas = {}
        if isinstance(full, dict) and isinstance(full.get("tools"), list):
            for t in full["tools"]:
                if isinstance(t, dict) and t.get("name"):
                    schemas[str(t["name"])] = t.get("parameters")
        for item in catalog:
            params = schemas.get(item["name"])
            if params is not None:
                item["parameters"] = params
        skills = opts.get("skills") if isinstance(opts, dict) and isinstance(opts.get("skills"), list) else []
        n = int(state.get("sys_no") or 0) + 1
        state["sys_no"] = n
        payload = {"prompt_text": prompt, "previous_prompt": state.get("last_prompt")}
        # 目录逐轮同质化：内容不变不重复落库，投影层前向填充补齐展示。
        fp = hashlib.sha1(json.dumps({"t": catalog, "s": skills}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if fp != state.get("catalog_fp"):
            payload["tools_catalog"] = catalog
            payload["skills_catalog"] = skills
        state["catalog_fp"] = fp
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="system.upserted",
            payload=payload,
            turn=None,
            ts=ts,
            eid=f"{session_id}:system:{n}",
        ))
        state["last_prompt"] = prompt
        return out
    if name == "agent_start":
        if not state.get("opened"):
            state["opened"] = True
            title = ctx.get("title") or session_id
            state["title_set"] = title != session_id
            payload = {"title": title, **identity}
            if ctx.get("channel"):
                payload["channel"] = str(ctx["channel"])
            lin = ctx.get("lineage") or {}
            parent = lin.get("PI_SUBAGENT_ORCHESTRATOR_SESSION_ID")
            if parent:
                payload["parent_session"] = str(parent)
            if lin:
                payload["subagent"] = {
                    "orchestrator_session": lin.get("PI_SUBAGENT_ORCHESTRATOR_SESSION_ID"),
                    "run_id": lin.get("PI_SUBAGENT_RUN_ID"),
                    "child_agent": lin.get("PI_SUBAGENT_CHILD_AGENT"),
                    "depth": lin.get("PI_SUBAGENT_PARENT_DEPTH"),
                }
            out.append(envelope(
                agent_id=agent_id,
                session_id=session_id,
                type_="session.opened",
                payload=payload,
                turn=None,
                ts=ts,
                eid=f"{session_id}:opened",
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
                    out.append(envelope(
                        agent_id=agent_id,
                        session_id=session_id,
                        type_="turn.started",
                        payload={},
                        turn=state["turn"],
                        ts=ts,
                        eid=f"{session_id}:turn:{state['turn']}:start",
                    ))
                # Pi 未显式命名会话时（getSessionName 未设置），标题取第一条用户消息。
                if not state.get("title_set") and (ctx.get("title") or "") in {"", session_id}:
                    first = _message_text(msg)
                    if first:
                        state["title_set"] = True
                        out.append(envelope(
                            agent_id=agent_id,
                            session_id=session_id,
                            type_="session.opened",
                            payload={"title": first[:80]},
                            turn=None,
                            ts=ts,
                            eid=f"{session_id}:opened:title",
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
            # 会话重放（session.opened 后补历史）没有 message_start，
            # 耗时不可得时写 None（未测量）而非 0（会被当成实测零毫秒）。
            duration = max(int(ts) - int(m_start), 0) if m_start else None
            state.setdefault("msg_dur", {})[mid] = duration
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": role,
                "text": text or "",
                "status": status,
                "request_no": req,
                "usage": usage,
                "started_at": int(msg.get("timestamp") or ts),
                "duration_ms": duration,
                "model": msg.get("model"),
                "provider": msg.get("provider"),
                "output_text": text if role == "assistant" else None,
            },
            turn=turn,
            ts=ts,
            eid=f"{session_id}:msg:{mid}:{name}",
        ))
        return out
    if name == "tool_execution_start":
        cid = str(event.get("toolCallId") or "")
        if not cid:
            return out
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        state.setdefault("tool_args", {})[cid] = args
        state.setdefault("tool_start_ts", {})[cid] = ts
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="tool.upserted",
            payload={
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
            turn=state.get("turn") or 1,
            ts=ts,
            eid=f"{session_id}:tool:{cid}:start",
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
        duration = max(int(ts) - int(start_ts), 0) if start_ts else None
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="tool.upserted",
            payload={
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
            turn=state.get("turn") or 1,
            ts=ts,
            eid=f"{session_id}:tool:{cid}:end",
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
                out.append(envelope(
                    agent_id=agent_id,
                    session_id=session_id,
                    type_="message.upserted",
                    payload={
                        "message_id": mid,
                        "role": "assistant",
                        "text": text or "",
                        "status": "completed",
                        "request_no": state.get("request_no") or 1,
                        "usage": usage,
                        "started_at": int(msg.get("timestamp") or ts),
                        "duration_ms": state.get("msg_dur", {}).get(mid),
                        "model": msg.get("model"),
                        "provider": msg.get("provider"),
                        "output_text": text,
                    },
                    turn=turn,
                    ts=ts,
                    eid=f"{session_id}:msg:{mid}:end",
                ))
        stop = (msg.get("stopReason") if isinstance(msg, dict) else None)
        status = {"error": "failed", "aborted": "cancelled"}.get(stop)
        # turn.ended 是部分轮次取 usage/model 的唯一来源，必须带归因字段。
        ended_payload = {
            "usage": usage,
            "model": msg.get("model"),
            "provider": msg.get("provider"),
        }
        if status:
            ended_payload["status"] = status
        out.append(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="turn.ended",
            payload=ended_payload,
            turn=turn,
            ts=ts,
            eid=f"{session_id}:turn:{turn}:end",
        ))
        return out
    # agent_end / agent_settled / 其他：不做收尾。以前把 agent_end 当会话结束，
    # 会在自动重试/续跑的下一次 agent run 之前提前关闭会话。
    return out


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
