"""适配器共享翻译词汇表（架构评审候选 1）。

五个适配器的 interface 很深（translate_line/hook → 事件列表），但共享约定
此前靠注释互相引用维系：信封逐字五份、工具双行协议三份、轮次递增三份变体、
usage 三态四份方言映射、「全 0 计 missing」判定三处各写一遍。占位时长 bug
（9a89d 修 pi 后 1d36d6 还要在消费端再防御一次）证明约定需要单一归属地。

这里只收真正同构的部分；各家方言差异（字段名映射、事件路由）留给适配器。
jsonl 适配器无状态机不参与；pi 走 hook 通道轮次逻辑不同构，只收 _ev 与
usage 两块。
"""
from __future__ import annotations

# claude/codex/droid 的「耗时未知」占位约定：转录不带耗时统一写 1，
# 消费端 summarize_timing 按 >PLACEHOLDER_MS 过滤。与 project.PLACEHOLDER_MS 同值。
PLACEHOLDER_MS = 1

# dsh 把非用户输入的注入消息标成 CONTEXT（system-reminder / skill 清单 /
# TodoWrite 提醒）。ATA 语料里这些仍走 user 角色：「CONTEXT 注入不算真实
# 用户消息、不开新轮」是翻译裁决（CONTEXT.md 明文挂在 CONTEXT 词条下），
# 唯一归属地在翻译内核；投影层改标 CONTEXT 同吃这份判定。
_CONTEXT_PREFIXES = (
    "<system-reminder>",
    "<system-notification>",
    "Skill \"",
    "Skill '",
)


def is_context_text(text):
    raw = (text or "").lstrip()
    return any(raw.startswith(prefix) for prefix in _CONTEXT_PREFIXES)


def make_ev(eid, agent_id, session_id, ts, typ, turn, payload):
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


_MISSING_SHAPE = {
    "status": "missing",
    "input": None, "output": None,
    "cache_read": None, "cache_write": None,
    "total_tokens": None, "cost": None,
}


def usage_missing():
    return dict(_MISSING_SHAPE)


def usage_from_counts(inp, outp, cache_read, cache_write, total_tokens=None, cost=None):
    """四元计数 → ATA usage。「全 0 计 missing」判定的唯一归属地。"""
    if not any((inp, outp, cache_read, cache_write)):
        return usage_missing()
    return {
        "status": "reported",
        "input": inp, "output": outp,
        "cache_read": cache_read, "cache_write": cache_write,
        "total_tokens": total_tokens, "cost": cost,
    }


def tool_start_payload(cid, parent_mid, name, args, text, started_at):
    """工具双行协议的 start 行 payload。state["tools"][cid] 存一份，
    end 行从 prev 回填 parent/payload/text/started_at（转录里 result 行不带这些）。"""
    return {
        "tool_call_id": cid,
        "parent_message_id": parent_mid,
        "name": name,
        "text": text,
        "status": "pending",
        "payload": args,
        "result": None,
        "started_at": started_at,
        "duration_ms": None,
    }


def tool_end_payload(prev, cid, parent_fallback, result, completed_at):
    """工具双行协议的 end 行 payload：从 start 存的 prev 回填，缺失走 fallback。"""
    prev = prev or {}
    return {
        "tool_call_id": cid,
        "parent_message_id": prev.get("parent_message_id") or parent_fallback,
        "name": prev.get("name") or "tool",
        "text": prev.get("text") or (result[:200] if result else cid),
        "status": "completed",
        "payload": prev.get("payload"),
        "result": result,
        "started_at": prev.get("started_at") or completed_at,
        "duration_ms": PLACEHOLDER_MS,
    }


def bump_turn_if_real_user(state, texts, agent_id, session_id, ts, emit):
    """真实用户消息才开新轮并补 turn.started；CONTEXT 注入不开轮。

    返回本轮轮次号（未开新轮返回当前轮或 None）。emit(event) 由调用方提供
    （通常是把事件 append 进输出列表的闭包）。started_turns 防同一轮重复发。
    """
    if is_context_text(texts):
        return state.get("turn") or None
    state["turn"] = int(state.get("turn") or 0) + 1
    turn = state["turn"]
    if turn not in state.setdefault("started_turns", set()):
        state["started_turns"].add(turn)
        emit(make_ev(
            f"{session_id}:turn:{turn}:start", agent_id, session_id, ts,
            "turn.started", turn, {},
        ))
    return turn
