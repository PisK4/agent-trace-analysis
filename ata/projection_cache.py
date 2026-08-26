"""便捷层投影缓存（架构评审候选 2）。

账本是 append-only，sessions.last_seq 天然是会话级版本号——GET /api/sessions/{id}
早已用它做 rev 门控短路，但 /usage /tools /tool-stats /timing 四个端点每次都
全量 read+重算。缓存的键是 (session_id, kind)，值带 rev；请求 rev 与缓存 rev
一致即回缓存。单进程内存态，服务重启即空，无需持久化——投影可重建是 CONTEXT.md
写明的性质。线程安全靠一把锁（HTTP handler 是 ThreadingHTTPServer 多线程）。
"""
from __future__ import annotations

import threading


class ProjectionCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[tuple[str, str], tuple[int, object]] = {}

    def get_or_compute(self, sid: str, rev: int, kind: str, compute):
        with self._lock:
            hit = self._slots.get((sid, kind))
            if hit is not None and hit[0] == rev:
                return hit[1]
            # compute 可能慢（全量 read+折叠），放锁外避免阻塞其他会话；
            # 竞态下同 kind 可能算两次，幂等无害。
        result = compute()
        with self._lock:
            self._slots[(sid, kind)] = (rev, result)
        return result

    def invalidate_prefix(self, sid: str) -> None:
        with self._lock:
            for key in [k for k in self._slots if k[0] == sid]:
                del self._slots[key]
