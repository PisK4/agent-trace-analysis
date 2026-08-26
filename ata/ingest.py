"""采集编排（架构评审二轮候选 6）：文件 tail 线程、droid 标题补写调度、
pi hook 状态桶的唯一归属地。

此前编排逻辑一半在 __main__（start_tail 三连 + droid refresh_loop 内联线程）、
一半在 http（_pi_states 靠 setattr 动态挂在 Ledger 对象上）——Ledger 毫不知情
却承载着采集状态，seam 错位。收进来后：__main__ 只说「开服务前把采集跑起来」，
http 的 hook 入口收缩成「校验 + 翻译 + 入账本」。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path


class PiHookStates:
    """pi 适配器的会话状态桶：session_id → translate_hook 的 state dict。

    pi 走 HTTP 推送、没有可 tail 的转录文件，翻译状态只能活在服务进程里；
    单进程单 writer，一把锁防 ThreadingHTTPServer 并发 setdefault 竞态。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[str, dict] = {}

    def bucket(self, session_id: str) -> dict:
        with self._lock:
            return self._states.setdefault(session_id, {"session_id": session_id})


def start_tails(ledger, *, tail_max_age_days, droid_path=None, claude_path=None,
                codex_path=None) -> None:
    """启动全部文件 tail 与 droid 标题补写线程（daemon）。显式传入的路径才打开，
    默认不碰厂商目录；pi 不走这里——它经 HTTP 推送，状态在 PiHookStates。
    """
    def start_tail(path_arg, translate_file):
        if not path_arg:
            return
        from ata.plugins.jsonl import tail_path
        # 目录/单文件统一走 tail_path：首轮灌入近期文件（账本按 id 幂等），
        # 之后 1s 轮询发现新文件与活动会话的追加行。
        threading.Thread(target=tail_path, args=(Path(path_arg), translate_file, ledger),
                         kwargs={"max_age_days": tail_max_age_days}, daemon=True).start()

    start_tail(droid_path, _droid_translate_file())
    if droid_path:
        # Droid 的真实标题在首条消息后才生成并原地重写 session_start 行，tail
        # 读不到；单独起线程定期按文件首行纠正账本标题。
        title_state: dict = {}  # {session_id: (mtime_ns, size)}，跨轮次持久持有
        def refresh_loop():
            from ata.plugins.droid import refresh_titles
            while True:
                time.sleep(15)
                try:
                    refresh_titles(Path(droid_path), ledger, title_state)
                except Exception:
                    pass  # 目录抖动下一轮再试，不拖死服务
        threading.Thread(target=refresh_loop, daemon=True).start()
    if claude_path:
        from ata.plugins.claude import translate_file as claude_tf
        start_tail(claude_path, claude_tf)
    if codex_path:
        from ata.plugins.codex import translate_file as codex_tf
        start_tail(codex_path, codex_tf)


def _droid_translate_file():
    from ata.plugins.droid import translate_file
    return translate_file
