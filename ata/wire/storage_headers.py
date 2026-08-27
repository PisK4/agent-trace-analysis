"""落档白名单唯一归属地（架构评审候选 2 重新定义后）。

代理壳把任意 headers 进来，本模块按 namespace 决定**哪些落账本**。判定只
影响 `record.request_headers` 字段，**不影响转发**——代理壳的转发逻辑保留
hop-by-hop 黑名单，hop-by-hop 之外的头一字不动转上游。

namespace 选择：
- x-claude-*：claude code CLI 实测带的请求头（x-claude-code-session-id 等）
- x-codex-*：codex CLI / OpenAI Responses API 客户端带的头（参考 ava 已声明
  的 x-codex-window-id / x-codex-parent-thread-id / x-codex-turn-metadata）
- x-droid-*：droid CLI 预期会带的头占位（具体头名待真实流量回填）

**绝不**落档：authorization / x-api-key / cookie 等认证头；content-type /
user-agent 等通用协议头（无 host 业务含义）。这些头由 capture_proxy 透传给
上游网关，落档侧一律不放行。

加新 agent 走代理：在这加一行 namespace 占位，list[namespace] 扩展为四家。
加新头：**必须**确认该头是 host 业务字段（如 sid / lineage 标识）才放行。
"""
from __future__ import annotations

#: 落档白名单 namespace。头名（小写）以其中之一为前缀才落账本。
#: 加新 agent 走代理：在这里加一行；具体头名由 ava 已声明的名单 + 真实流量验证。
STORAGE_HEADER_NAMESPACES: tuple[str, ...] = (
    "x-claude-",
    "x-codex-",
    "x-droid-",
)

#: droid 头占位——具体头名待真实流量回填。占位存在是为了让
#: STORAGE_HEADER_NAMESPACES 含 x-droid- 的事实**被一处声明**而不是散落。
#: 真实头名回填时，在下面 frozenset 内加具体名（大小写不敏感）。
_DROID_HEADERS_TBD: frozenset[str] = frozenset()


def record_headers_for_storage(headers):
    """过滤 headers：只保留 namespace 在白名单内的头。

    大小写不敏感（HTTP header 名按规范是 case-insensitive）；返回值保留
    原始大小写（即 client 原样发什么就存什么）。

    返回值是 dict 副本，调用方安全持有。
    """
    if not headers:
        return {}
    out = {}
    for k, v in headers.items():
        lower = str(k).lower()
        if any(lower.startswith(ns) for ns in STORAGE_HEADER_NAMESPACES):
            out[k] = v
    return out
