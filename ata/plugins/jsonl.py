from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path


def iso_to_ms(value, fallback: int = 1) -> int:
    """ISO 8601 字符串或 Unix 秒/毫秒 → Unix 毫秒。解析失败用 fallback。"""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return int(value) if value > 10**12 else int(value * 1000)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        return fallback


def translate_file(path: Path, translate_line, offset: int = 0, state: dict | None = None):
    """按字节偏移增量读一个 JSONL 文件，半行留到下次。

    translate_line(raw: dict, state: dict) -> list[dict] 由各插件提供。
    droid.py 内还有一份更早的同形实现；第三个插件落地后统一迁到这里。

    state: 跨 step 持久化的 per-file 状态桶（turn / last_assistant_id / tools
    等），由调用方（step_tail）注入；不传则回退到旧行为：每次调用都新建
    {"session_id": <path.stem>}，turn 等累加器会丢——这是 trace 显示异常
    根因之一，新代码**必须**传。
    """
    # seek 到 offset 只读剩余字节，目录 tail 每轮全扫时不会反复读整个大文件。
    with open(path, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n") and b"\n" in chunk:
        keep = text.rfind("\n") + 1
        rest = text[:keep]
        new_offset = offset + len(rest.encode("utf-8"))
    else:
        rest = text
        new_offset = offset + len(chunk)
    if state is None:
        # 生产 tail 必须传入持久 state；无 state 时不猜 session_id。
        # 直接插件测试由各自 wrapper 提供 stem 兼容桶。
        state = {}
    events = []
    for line in rest.splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except (ValueError, TypeError):
            # 运行中写入一半的行、或厂商文件自身的损坏行：跳过，不拖垮整个会话。
            continue
        events.extend(translate_line(raw, state))
    return events, new_offset


def step_tail(root: Path, translate_file_fn, ledger, state: dict, max_age_days: int | None = None) -> list:
    """扫 root（目录递归或单文件），对 size 增长的 JSONL 增量翻译并追加账本。

    max_age_days：目录模式下跳过 mtime 早于该天数的历史文件（手动测试只关心近期
    会话；全历史灌入会让厂商目录动辄几 GB）。None 表示不做限制。
    state: {str(path): {"offset": int, "translate": dict}}，offset 持久持有、
    translate 透传给 translate_file 跨 step 累积（turn / last_assistant_id / tools
    等）。返回本批事件（测试用）。
    """
    from ata.schema import parse_event
    root = Path(root)
    if root.is_dir():
        files = sorted(root.rglob("*.jsonl"))
    elif root.is_file():
        files = [root]
    else:
        return []
    cutoff = None
    if max_age_days is not None:
        cutoff = time.time() - max_age_days * 86400
    batch = []
    for f in files:
        try:
            st = f.stat()
            size = st.st_size
            if cutoff is not None and st.st_mtime < cutoff:
                continue
        except OSError:
            continue
        # per-file 桶: 兼容老 state（纯 int offset）——首次见到的 path 自动升格。
        bucket = state.get(str(f))
        if bucket is None or isinstance(bucket, int):
            bucket = {"offset": int(bucket) if isinstance(bucket, int) else 0,
                      "translate": {}}
            state[str(f)] = bucket
        if size <= bucket["offset"]:
            continue
        events, new_offset = translate_file_fn(
            f, bucket["offset"], bucket["translate"])
        # 跨 file 切换时 plugin 把上一 file 的 flush 暂存在 _pre_flush,先捞出来。
        pre = bucket["translate"].pop("_pre_flush", None) or []
        all_events = pre + events
        if all_events:
            parsed = [parse_event(ev) for ev in all_events]
            ledger.append_many(parsed)  # 一批一次 commit，减 WAL 抖动
        batch.extend(all_events)
        bucket["offset"] = new_offset
    return batch


def tail_path(path: Path, translate_file_fn, ledger, max_age_days: int | None = None):
    """1s 轮询：目录递归 / 单文件都支持，首轮即灌入近期文件（账本按 id 幂等）。"""
    state = {}
    while True:
        try:
            step_tail(path, translate_file_fn, ledger, state, max_age_days)
        except Exception:
            # 目录被删/权限抖动：下一轮再试，不拖死整个服务。
            pass
        time.sleep(1)
