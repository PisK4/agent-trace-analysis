"""代理采集适配器（架构评审候选 1+2）：wire 流量 → 规范事件。

身份规则（候选 2，本模块的 interface 一部分）：从请求头恢复宿主
sessionId，往同一 session 追加，幂等键吸收重复；恢复不了就丢弃，
绝不新建孤儿会话——ava 把会话归并推迟到读取侧，ata 是写入时收敛，
平行会话会让投影/usage 合计翻倍。

v1 只发账本里别处拿不到的事实：system.upserted（prompt_text +
tools_catalog，transcript 侧 claude 永远发不出）与 turn.ended（每轮
真实 usage，spec L214 的立项痛点）。message/tool 行 transcript 已有，
代理重复发会在两条通道间产生 natural-key 写序竞态，刻意不发。
"""
from __future__ import annotations

import hashlib
import json

from ata.plugins.common import tool_end_payload, tool_start_payload, usage_from_counts
from ata.schema import envelope
from ata.wire import parse_request as _wire_req
from ata.wire import parse_response as _wire_resp

# 各家宿主携带会话 id 的请求头（小写）。cue/pi/droid 若走代理，按此表头加行。
# 头名匹配大小写不敏感；命中即返回（不再走 body 路径）。
_SESSION_HEADERS: dict[str, tuple[str, ...]] = {
    "claude": ("x-claude-code-session-id",),
}

# 各家宿主把会话 id 放在请求体字段（按 JSON 嵌套路径定位）。
# codex 走 OpenAI Responses API，session_id 在 metadata.session_id。
# droid 路径占位（具体字段名待真实流量回填——若 droid 用 body metadata，
# 在此加；若是 header，移到 _SESSION_HEADERS）。
_BODY_SESSION_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "codex": (("metadata", "session_id"),),
}


def _dig(payload, path):
    """按嵌套路径取 dict 值；任一环不是 dict 或缺 key 返回 None。"""
    cur = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def resolve_session_id(rec, agent_id):
    """从 record 恢复宿主 sessionId；找不到返回 None（调用方丢弃该次采集）。

    优先 headers 路径（claude 走此），回退 body 路径（codex 走 OpenAI
    Responses API 的 metadata.session_id）。两条路径都未声明 = 暂未支持。

    caller 已注入 `rec["session_id"]` 时（如 capture_proxy 给 droid 注入
    虚拟 sid）优先使用——这是「caller 已识别该 record 归属」的明确信号,
    避免重复解析 headers / body。
    """
    if rec and isinstance(rec.get("session_id"), str):
        injected = rec["session_id"].strip()
        if injected:
            return injected
    headers = (rec or {}).get("request_headers") or {}
    low = {str(k).lower(): v for k, v in headers.items()}
    for name in _SESSION_HEADERS.get(agent_id, ()):
        sid = low.get(name)
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    body_paths = _BODY_SESSION_FIELDS.get(agent_id, ())
    if body_paths:
        try:
            payload = json.loads(
                (rec.get("request_body") or b"").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return None
        if isinstance(payload, dict):
            for path in body_paths:
                v = _dig(payload, path)
                if isinstance(v, str) and v.strip():
                    return v.strip()
    return None


def _user_text_from_item(item):
    """从 wire summary 的 message_item 提 user 角色文本。

    吃 anthropic_parser 已解析的 message_items 形状（role + 摘要 text 字段），
    原始 content blocks 已被 _content_blocks 压平成 text 字符串。tool_use
    / tool_result / 助手行都不算 user 文本。
    """
    if not isinstance(item, dict) or item.get("role") != "user":
        return ""
    text = item.get("text")
    return text if isinstance(text, str) else ""


def count_real_user_turns(message_items):
    """wire message_items 里的真实 user 消息数 = 当前轮次号。

    与 jsonl 侧 bump_turn_if_real_user 同口径：CONTEXT 注入不开轮
    （复用 ata.project.is_context_text，懒加载避免循环导入）。
    """
    from ata.project import is_context_text

    count = 0
    for item in message_items or []:
        text = _user_text_from_item(item)
        if not text or is_context_text(text):
            continue
        count += 1
    return count


#: record 形状的唯一声明（shell 与 HTTP 端点共同遵守）。
RECORD_KEYS = frozenset({
    "agent_id", "path", "request_headers", "request_body",
    "response_content_type", "response_body",
    "started_at_ms", "completed_at_ms",
})


def state_bucket(ledger, sid):
    """按 session 分桶的翻译状态，挂在 ledger 上（与 _pi_states 同款约定）。"""
    states = getattr(ledger, "_capture_states", None)
    if states is None:
        ledger._capture_states = {}
        states = ledger._capture_states
    return states.setdefault(sid, {"session_id": sid})


def _catalog(tool_items):
    return [
        {
            "name": item.get("name"),
            "description": item.get("description"),
            "parameters": item.get("parameters"),
        }
        for item in (tool_items or [])
        if isinstance(item, dict) and item.get("name")
    ]


def _system_hash(prompt_text, catalog):
    blob = json.dumps(
        {"p": prompt_text, "t": catalog}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def translate_capture(rec, state):
    """一次截获的请求/响应对 → 规范事件列表。永不抛（坏输入返回 []）。"""
    try:
        return _translate(rec, state)
    except Exception as exc:  # noqa: BLE001 —— 采集绝不弄挂被代理请求
        print(f"capture translate error: {exc}")
        return []


def _translate(rec, state):
    path = rec.get("path") or ""
    body = rec.get("request_body") or b""
    req = _wire_req(path, rec.get("request_headers") or {}, body)
    resp = _wire_resp(path, {}, rec.get("response_content_type") or "",
                      rec.get("response_body") or b"")
    out = []
    ts = int(rec.get("completed_at_ms") or rec.get("started_at_ms") or 1)
    agent_id = rec.get("agent_id") or "claude"
    sid = state.get("session_id")

    # SYSTEM 快照 + tools 目录：只在内容变化时发（system.upserted 无自然键，
    # 每次请求都带全文，不去重会把账本灌爆）。
    prompt_text = "\n\n".join(req.get("system_prompts") or [])
    catalog = _catalog(req.get("tool_items"))
    if prompt_text:
        h = _system_hash(prompt_text, catalog)
        if h != state.get("system_hash"):
            state["system_hash"] = h
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="system.upserted",
                payload={"prompt_text": prompt_text, "tools_catalog": catalog},
                turn=None,
                ts=ts,
                eid=f"{sid}:system:{h}",
            ))

    # 每轮真实 usage：轮次号 = 请求上下文真实用户消息数（与 transcript 侧
    # bump_turn_if_real_user 同口径，两条通道才能落在同一 turn 上）。
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    inp = int(usage.get("input_tokens") or 0)
    outp = int(usage.get("output_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    cw = int(usage.get("cache_creation_input_tokens") or 0)
    started = int(rec.get("started_at_ms") or ts)
    completed = int(rec.get("completed_at_ms") or ts)
    duration = completed - started

    # message.upserted (user + assistant): 代理主发, transcript 侧不再发
    # message 行 (transcript 仍发 ai-title / compact_boundary / system.api_error
    # 等元数据)。state["_capture_emit"] 跟踪本 sid 已 emit 的 message_id, 防重。
    seen = state.setdefault("_capture_emit", set())
    message_items = req.get("message_items") or []
    turn = count_real_user_turns(message_items)
    if turn < 1:
        turn = 1

    # user messages from request (跟 count_real_user_turns 同口径过滤
    # CONTEXT 注入, 避免 <system-reminder> 被当 user 消息写入)
    from ata.project import is_context_text as _is_ctx
    for m in req.get("messages") or []:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        # 先把 content 拼成 preview_text, 跟 count_real_user_turns 一致判断
        content = m.get("content")
        if isinstance(content, str):
            preview_text = content
        elif isinstance(content, list):
            preview_text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
                and isinstance(b.get("text"), str)
            )
        else:
            preview_text = ""
        if not preview_text or _is_ctx(preview_text):
            continue
        mid = str(m.get("id") or f"{sid}:user:{m.get('index', '')}")
        if mid in seen:
            continue
        seen.add(mid)
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            blocks = [b for b in content if isinstance(b, dict)]
        else:
            blocks = []
        text_joined = preview_text
        # 跳过纯 tool_result 块 (没有文本 user)
        if not text_joined and not any(
            isinstance(b, dict) and b.get("type") != "tool_result" for b in blocks
        ):
            continue
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="message.upserted",
            payload={
                "message_id": mid,
                "role": "user",
                "text": text_joined[:200],
                "status": "completed",
                "request_no": None,
                "usage": None,
                "started_at": started,
                "duration_ms": duration,
                "output_text": None,
                "thinking": None,
                "model": None,
            },
            turn=turn,
            ts=ts,
            eid=f"{sid}:msg:{mid}",
        ))

    # assistant message from response (only if response_id present)
    resp_id = resp.get("response_id")
    if isinstance(resp_id, str) and resp_id:
        if resp_id not in seen:
            seen.add(resp_id)
            blocks = resp.get("response_blocks") or []
            texts, thinking_parts = [], []
            for b in blocks:
                if isinstance(b, dict):
                    btype = b.get("type")
                    if btype == "text" and isinstance(b.get("text"), str):
                        texts.append(b["text"])
                    elif btype == "thinking" and isinstance(b.get("thinking"), str):
                        thinking_parts.append(b["thinking"])
            text_joined = "\n".join(texts)
            thinking_joined = "\n".join(thinking_parts) or None
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="message.upserted",
                payload={
                    "message_id": resp_id,
                    "role": "assistant",
                    "text": text_joined[:200],
                    "status": "completed",
                    "request_no": turn,
                    "usage": usage_from_counts(
                        inp, outp, cr, cw,
                        total_tokens=inp + outp + cr + cw) if (inp or outp or cr or cw) else None,
                    "started_at": started,
                    "duration_ms": duration,
                    "output_text": text_joined or None,
                    "thinking": thinking_joined,
                    "model": req.get("model"),
                },
                turn=turn,
                ts=ts,
                eid=f"{sid}:msg:{resp_id}",
            ))

    if inp or outp or cr or cw:
        if turn >= 1:
            rid = resp.get("response_id")
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="turn.ended",
                payload={"usage": usage_from_counts(
                    inp, outp, cr, cw, total_tokens=inp + outp + cr + cw)},
                turn=turn,
                ts=ts,
                eid=f"{sid}:turn:{turn}:ended:{rid or ts}",
            ))

    # tool.upserted: start 从 response.tool_calls 提, end 从本 request 的
    # tool_result 块提 (响应里没有 result — 它在下一次请求里)。
    tools_state = state.setdefault("_capture_tools", {})
    response_id = resp.get("response_id")

    # start
    for tc in resp.get("response_tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        cid = tc.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        if cid in tools_state:
            continue
        name = tc.get("name") or "tool"
        args = tc.get("input") if isinstance(tc.get("input"), dict) else {}
        text = args.get("path") or args.get("pattern") or name
        # 字段名与 common.tool_end_payload 期望对齐 (parent_message_id / payload /
        # text / started_at, 缺失 fallback 走 captured 路径)。
        tools_state[cid] = {
            "name": name, "payload": args, "text": text,
            "parent_message_id": response_id,
            "started_at": started,
        }
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="tool.upserted",
            payload=tool_start_payload(cid, response_id, name, args, text, started),
            turn=turn,
            ts=ts,
            eid=f"{sid}:tool:{cid}:start",
        ))

    # end: 扫本 request 全部 messages 的 tool_result 块
    for m in req.get("messages") or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            cid = b.get("tool_use_id")
            if not isinstance(cid, str) or not cid:
                continue
            if cid not in tools_state:
                continue  # 没有对应 start (代理漏了一次响应), 不发 end
            prev = tools_state.pop(cid)
            res = b.get("content")
            if isinstance(res, list):
                res = "\n".join(
                    bb.get("text", "") for bb in res
                    if isinstance(bb, dict) and isinstance(bb.get("text"), str)
                )
            res_text = res if isinstance(res, str) else ""
            out.append(envelope(
                agent_id=agent_id,
                session_id=sid,
                type_="tool.upserted",
                payload=tool_end_payload(prev, cid, response_id, res_text, completed),
                turn=turn,
                ts=ts,
                eid=f"{sid}:tool:{cid}:end",
            ))

    return out


def ingest_capture(ledger, rec):
    """解析 → 校验 → 入账本。返回写入数；校验失败抛 ValidationError。

    身份规则在此收口：恢复不出宿主 sessionId 就抛错丢弃（进程内壳吞掉，
    HTTP 端点回 400），绝不造 sid 新建孤儿会话。
    """
    from ata.schema import parse_event

    agent_id = rec.get("agent_id") or "claude"
    sid = resolve_session_id(rec, agent_id)
    if not sid:
        raise ValueError("capture: no host session id; dropping (no orphan sessions)")
    state = state_bucket(ledger, sid)
    state["session_id"] = sid
    events = [parse_event(ev) for ev in translate_capture(rec, state)]
    if events:
        ledger.append_many(events)
    return len(events)
