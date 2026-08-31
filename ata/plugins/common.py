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

from ata.schema import envelope

# claude/codex/droid 的「耗时未知」占位约定：转录不带耗时统一写 1，
# 消费端 summarize_timing 按 >PLACEHOLDER_MS 过滤。与 project.PLACEHOLDER_MS 同值。
PLACEHOLDER_MS = 1

# dsh 把非用户输入的注入消息标成 CONTEXT（system-reminder / skill 清单 /
# TodoWrite 提醒）。ATA 语料里这些仍走 user 角色：「CONTEXT 注入不算真实
# 用户消息、不开新轮」是翻译裁决（CONTEXT.md 明文挂在 CONTEXT 词条下），
# 唯一归属地在翻译内核；投影层改标 CONTEXT 同吃这份判定。
#
# 判定走「形态学 + id 守门」双保险（2026-08-27 治本改造）：
#   1. 形态学: 文本以 <xxx> / [BRACKETED_KEY] / Skill " 开头 → CONTEXT
#      不枚举 tag、不要求闭合, 新形态 (<ide_selection> / <something-else>)
#      自动命中, 永远不漏
#   2. id 守门: 文本像 CONTEXT 但所在块带 wire id 字段 → 真 user, 不判 CONTEXT
#      harness 自造注入时**不**给 id; 真实 user 消息 wire 带 id 是不变量
#      (统计 ~/.ata/ata.sqlite: 所有 <xxx>...</xxx> 形态 user 消息实测 100%
#      是 harness 注入, 真 user 写 HTML 形态 0 样本)
#
# 参考: repos/agent-visualization-analysis/trace_graph.py:2157-2169
#       (ava 的 _INJECTED_BLOCK_RE 用形态学闭合块剥注入, 思路一致)
_BRACKET_HEAD = "["
_SKILL_HEAD_DOUBLE = 'Skill "'
_SKILL_HEAD_SINGLE = "Skill '"

# 纯文本形态的 harness 注入 (无 <xxx> / [KEY] 标记, 形态学抓不到, 只能
# 按已知前缀枚举)。新形态优先观察是否带 wire id 走 id 守门, 真要漏再进
# 这张表 — 表越长误杀风险越大, 保持最小集。
_PLAIN_INJECTION_PREFIXES: tuple[str, ...] = (
    # Claude Code: user 走开后的自动 recap 指令 (sid 74736c29 user:3:11 实证)
    "The user stepped away and is coming back.",
)


def is_context_text(text, *, has_id: bool = False):
    """返回 True 表示文本是 CONTEXT 注入 (harness 注入), 不是真 user 提问。

    has_id: 文本所在 message 块是否带 wire id 字段。True 时豁免所有形态学
    判据 (id 守门保险, harness 构造注入从不打 id)。
    """
    if has_id:
        # id 守门: 块带 wire id → 必真 user, 任何启发式都不判 CONTEXT
        return False
    raw = (text or "").lstrip()
    if not raw:
        return False
    # 纯文本已知注入前缀 (recap 指令等)
    if raw.startswith(_PLAIN_INJECTION_PREFIXES):
        return True
    # 形态学贪心: <xxx> 任意 tag, 不枚举, 不要求闭合
    if raw[0] == "<":
        return True
    # [...] 形态, 例如 [CURRENT_TIME] / [MATERIAL_WINDOW] / 任何 [BRACKETED_KEY]
    if raw[0] == _BRACKET_HEAD:
        return True
    # Skill 自动加载提示
    if raw.startswith((_SKILL_HEAD_DOUBLE, _SKILL_HEAD_SINGLE)):
        return True
    return False


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
        emit(envelope(
            agent_id=agent_id,
            session_id=session_id,
            type_="turn.started",
            payload={},
            observed_turn_ordinal=turn,
            ts=ts,
            eid=f"{session_id}:turn:{turn}:start",
        ))
    return turn
