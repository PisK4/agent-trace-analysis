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
