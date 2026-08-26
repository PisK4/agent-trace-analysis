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

from ata.plugins.common import usage_from_counts
from ata.schema import envelope
from ata.wire import parse_request as _wire_req
from ata.wire import parse_response as _wire_resp

# 各家宿主携带会话 id 的请求头（小写）。cue/pi 若走代理，加行即可。
_SESSION_HEADERS = {
    "claude": ("x-claude-code-session-id",),
}


def resolve_session_id(headers, agent_id):
    low = {str(k).lower(): v for k, v in (headers or {}).items()}
    for name in _SESSION_HEADERS.get(agent_id, ()):
        sid = low.get(name)
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
    return None


def _block_texts(content):
    """消息 content 里的文本拼接；字符串/块数组/裸字符串数组都吃。"""
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def count_real_user_turns(messages):
    """请求上下文的真实用户消息数 = 当前轮次号。

    与 jsonl 侧 bump_turn_if_real_user 同口径：CONTEXT 注入不开轮
    （复用 ata.project.is_context_text，懒加载避免循环导入，同 common.py）。
    """
    from ata.project import is_context_text

    count = 0
    for msg in messages if isinstance(messages, list) else []:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        text = _block_texts(msg.get("content"))
        # 无文本的畸形 user 消息不算真实轮次。
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
    if inp or outp or cr or cw:
        messages = []
        try:
            messages = json.loads(body.decode("utf-8")).get("messages") or []
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        turn = count_real_user_turns(messages)
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
    return out


def ingest_capture(ledger, rec):
    """解析 → 校验 → 入账本。返回写入数；校验失败抛 ValidationError。

    身份规则在此收口：恢复不出宿主 sessionId 就抛错丢弃（进程内壳吞掉，
    HTTP 端点回 400），绝不造 sid 新建孤儿会话。
    """
    from ata.schema import parse_event

    headers = rec.get("request_headers") or {}
    agent_id = rec.get("agent_id") or "claude"
    sid = resolve_session_id(headers, agent_id)
    if not sid:
        raise ValueError("capture: no host session id; dropping (no orphan sessions)")
    state = state_bucket(ledger, sid)
    state["session_id"] = sid
    events = [parse_event(ev) for ev in translate_capture(rec, state)]
    if events:
        ledger.append_many(events)
    return len(events)
