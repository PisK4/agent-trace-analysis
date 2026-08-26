"""便捷层投影缓存（架构评审候选 2；二轮候选 3 收敛键形状）。

账本是 append-only，sessions.last_seq 天然是会话级版本号——GET /api/sessions/{id}
早已用它做 rev 门控短路，但 /usage /tools /tool-stats /timing 四个端点每次都
全量 read+重算。四个端点的 compute 是同一份 ledger.read(sid)，缓存键因此就是
session_id 本身：同会话同 rev 只持一份快照，body 组装在缓存外每请求执行。
单进程内存态，服务重启即空，无需持久化——投影可重建是 CONTEXT.md 写明的性质。
线程安全靠一把锁（HTTP handler 是 ThreadingHTTPServer 多线程）。
"""
from __future__ import annotations

import threading


class ProjectionCache:
    # 槽位上限：每个槽持有整份 json.loads 后的事件列表，不设上限的话长期运行
    # 的 serve 进程 RSS 单调上涨。超限按 FIFO 淘汰——rev 门控保证被淘汰的槽
    # 下次请求原样重算，无正确性影响。
    MAX_SLOTS = 256

    def __init__(self):
        self._lock = threading.Lock()
        self._slots: dict[str, tuple[int, object]] = {}

    def get_or_compute(self, sid: str, rev: int, compute):
        with self._lock:
            hit = self._slots.get(sid)
            if hit is not None and hit[0] == rev:
                return hit[1]
            # compute 可能慢（全量 read+折叠），放锁外避免阻塞其他会话；
            # 竞态下同会话可能算两次，幂等无害。
        result = compute()
        with self._lock:
            cur = self._slots.get(sid)
            # 只允许新 rev 覆盖旧 rev：慢的旧 rev 计算晚到时不得回退已就位的
            # 新结果（否则并发轮询下多一次冗余重算）。
            if cur is None or cur[0] <= rev:
                if len(self._slots) >= self.MAX_SLOTS and sid not in self._slots:
                    self._slots.pop(next(iter(self._slots)))
                self._slots[sid] = (rev, result)
        return result
