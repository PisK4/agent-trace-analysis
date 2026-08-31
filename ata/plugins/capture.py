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


def _user_texts_from_item(item):
    """从 wire summary 的 message_item 提 user 角色的 block 级文本列表。

    吃 anthropic_parser / openai_parser 已解析的 message_items 形状。
    texts (block 级列表) 存在时优先 — 注入块与真实提问同消息共存时按
    block 判, 只杀注入块; 旧 shape (无 texts) 退回压平的 text 字符串
    整串判。tool_use / tool_result / 助手行都不算 user 文本。
    """
    if not isinstance(item, dict) or item.get("role") != "user":
        return []
    texts = item.get("texts")
    if isinstance(texts, list):
        return [t for t in texts if isinstance(t, str)]
    text = item.get("text")
    return [text] if isinstance(text, str) and text else []


def _user_text_from_item(item):
    """压平的 user 文本 (旧接口, 仅供兼容; 过滤请走 _user_texts_from_item)。"""
    return "\n".join(_user_texts_from_item(item))


def _user_has_id_from_item(item):
    """message_item 是否带 wire id 字段 (anthropic_parser._message_items
    在 2026-08-27 治本改造里透出 has_id, 给 is_context_text 当 id 守门用)。
    缺字段视为 False (没 id 视为注入嫌疑, 让形态学判)。"""
    if not isinstance(item, dict):
        return False
    return bool(item.get("has_id"))


def real_user_blocks(item):
    """一条 user message_item 过滤 CONTEXT 注入块后剩下的真实文本 block。

    过滤粒度是 block 不是消息: Claude Code 常把 <local-command-caveat> 等
    注入与真实提问放进同一 user 消息的相邻 text block, 整串判形态学时
    开头的 <xxx> 会把真实提问连带杀掉 (sid 74736c29「你是谁」实证)。
    消息带 wire id 时整条豁免 (id 守门)。
    """
    from ata.project import is_context_text

    if not isinstance(item, dict):
        return []
    texts = _user_texts_from_item(item)
    if not texts:
        return []
    if _user_has_id_from_item(item):
        return texts
    return [t for t in texts if t and not is_context_text(t)]


def count_real_user_turns(message_items):
    """wire message_items 里的真实 user 消息数 = 当前轮次号。

    与 jsonl 侧 bump_turn_if_real_user 同口径：CONTEXT 注入不开轮
    （复用 ata.project.is_context_text，懒加载避免循环导入）。
    一条消息只剩注入块时不计数; 混合消息 (注入块 + 真实提问) 算一条。
    id 守门: 块带 wire id 时豁免形态学判据, 避免误杀真 user 写 <xxx> 形态。
    """
    count = 0
    for item in message_items or []:
        if real_user_blocks(item):
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


def _nonnegative_int(value):
    return value if type(value) is int and value >= 0 else 0


def _capture_usage(raw):
    if not isinstance(raw, dict):
        return None

    inp = _nonnegative_int(raw.get("input_tokens"))
    if not inp:
        inp = _nonnegative_int(raw.get("prompt_tokens"))
    outp = _nonnegative_int(raw.get("output_tokens"))
    if not outp:
        outp = _nonnegative_int(raw.get("completion_tokens"))

    cache_read = _nonnegative_int(raw.get("cache_read_input_tokens"))
    if not cache_read:
        cache_read = _nonnegative_int(raw.get("cached_input_tokens"))
    for key in ("input_tokens_details", "prompt_tokens_details"):
        details = raw.get(key)
        if not cache_read and isinstance(details, dict):
            cache_read = _nonnegative_int(details.get("cached_tokens"))

    cache_write = _nonnegative_int(raw.get("cache_creation_input_tokens"))
    if not cache_write:
        cache_write = _nonnegative_int(raw.get("cache_write_input_tokens"))

    if not any((inp, outp, cache_read, cache_write)):
        return None

    total = _nonnegative_int(raw.get("total_tokens"))
    if not total:
        total = inp + outp + cache_read + cache_write
    return usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=total)


def _assistant_parts(resp):
    text_parts = []
    thinking_parts = []
    blocks = resp.get("response_blocks") or []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block.get("type") == "thinking" and isinstance(block.get("thinking"), str):
            thinking_parts.append(block["thinking"])

    text = "\n".join(text_parts)
    if not text:
        for key in ("assistant_text", "response_text"):
            value = resp.get(key)
            if isinstance(value, str):
                text = value
                break
    thinking = "\n".join(thinking_parts) or None
    return text, thinking


def _capture_result_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            item.get("text", "")
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def _request_tool_results(req):
    results = []

    # OpenAI Chat Completions and Responses are represented by message_items;
    # both use role=tool and expose the pairing id in one of these two fields.
    for item in req.get("message_items") or []:
        if not isinstance(item, dict) or item.get("role") != "tool":
            continue
        cid = item.get("tool_call_id") or item.get("call_id")
        if isinstance(cid, str) and cid:
            results.append((cid, item.get("text") or ""))

    # Anthropic keeps tool_result inside a role=user content block; this is the
    # only request shape not represented as role=tool by the shared summary.
    for message in req.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            cid = block.get("tool_use_id")
            if isinstance(cid, str) and cid:
                results.append((cid, _capture_result_text(block.get("content"))))
    return results


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
                ts=ts,
                eid=f"{sid}:system:{h}",
            ))

    # 每轮真实 usage：轮次号 = 请求上下文真实用户消息数（与 transcript 侧
    # bump_turn_if_real_user 同口径，两条通道才能落在同一 turn 上）。
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    normalized_usage = _capture_usage(usage)
    started = int(rec.get("started_at_ms") or ts)
    completed = int(rec.get("completed_at_ms") or ts)
    duration = completed - started

    # message.upserted (user + assistant): 代理主发, transcript 侧不再发
    # message 行 (transcript 仍发 ai-title / compact_boundary / system.api_error
    # 等元数据)。防重走 events.dedupe_key UNIQUE 索引, 跨进程持久,
    # 不再在内存维护 seen set (跨进程丢, 重启后空 mid 又能 emit)。
    message_items = req.get("message_items") or []
    turn = count_real_user_turns(message_items)
    if turn < 1:
        turn = 1

    # user messages from request: block 级过滤 CONTEXT 注入 (同一消息里
    # 注入块 + 真实提问共存时只杀注入块, 整串判会连带杀掉真实提问),
    # 与 count_real_user_turns 同口径 (real_user_blocks)。
    # 每条真实 user 消息的 turn = 它的序号 (第 N 条真实 user = turn N),
    # 与 turn.ended 的 turn (总数 count) 自然对齐: 最后一条真实 user 的
    # turn 恰是本轮号, 历史 user 标各自的历史轮号。
    user_idx = -1   # user 消息下标 (含纯注入消息, mid 定位用)
    real_ordinal = 0  # 真实 user 序号 (turn 字段用)
    for item in message_items:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        user_idx += 1
        blocks = real_user_blocks(item)
        if not blocks:
            continue
        real_ordinal += 1
        text_joined = "\n".join(blocks)
        # mid 跨轮稳定: 每轮请求都重放全部历史 user 消息, mid 含 turn 号
        # 时同一条消息每轮换新 mid 重复入账 (sid 74736c29「你能做什么?」
        # 记了 3 次)。去掉 turn 号, 用 user 消息下标 + 内容哈希双键:
        # 下标定位, 哈希防同下标不同内容 (罕见的前插场景)。
        raw_mid = item.get("id")
        if not isinstance(raw_mid, str) or not raw_mid:
            h = hashlib.sha1(
                text_joined.encode("utf-8")).hexdigest()[:8]
            raw_mid = f"{sid}:user:{user_idx}:{h}"
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="message.upserted",
            payload={
                "message_id": raw_mid,
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
            observed_turn_ordinal=real_ordinal,
            ts=ts,
            eid=f"{sid}:msg:{raw_mid}",
        ))

    # assistant message from response (only if response_id present)
    resp_id = resp.get("response_id")
    if isinstance(resp_id, str) and resp_id:
        # dedupe_key 走 Ledger 层兜底, 翻译层不再用 seen 内存 set
        text_joined, thinking_joined = _assistant_parts(resp)
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
                "usage": normalized_usage,
                "started_at": started,
                "duration_ms": duration,
                "output_text": text_joined or None,
                "thinking": thinking_joined,
                "model": req.get("model"),
            },
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{sid}:msg:{resp_id}",
        ))

    if normalized_usage and turn >= 1:
        rid = resp.get("response_id")
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="turn.ended",
            payload={"usage": normalized_usage},
            observed_turn_ordinal=turn,
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
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{sid}:tool:{cid}:start",
        ))

    # end: 扫本 request 的标准化 tool result 摘要
    for cid, res_text in _request_tool_results(req):
        if cid not in tools_state:
            continue  # 没有对应 start (代理漏了一次响应), 不发 end
        prev = tools_state.pop(cid)
        out.append(envelope(
            agent_id=agent_id,
            session_id=sid,
            type_="tool.upserted",
            payload=tool_end_payload(prev, cid, response_id, res_text, completed),
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{sid}:tool:{cid}:end",
        ))

    return out


def _append_with_dedupe(ledger, events):
    """逐条 append; 命中 events.dedupe_key UNIQUE 索引时静默跳过。
    跨进程 seen 持久化兜底; 不再在内存维护 seen set。

    整批先尝试 append_many (单事务快, e2e 跟得上 ingest 节奏);
    失败时 (某条 UNIQUE 冲突) 回退到单条, 让 IntegrityError 走吞掉。
    """
    import sqlite3
    if not events:
        return 0
    try:
        ledger.append_many(events)
        return len(events)
    except sqlite3.IntegrityError:
        pass
    written = 0
    for ev in events:
        try:
            ledger.append(ev)
            written += 1
        except sqlite3.IntegrityError:
            continue
    return written


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
        return _append_with_dedupe(ledger, events)
    return 0
