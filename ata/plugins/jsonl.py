from __future__ import annotations

import json
import time
from datetime import datetime
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


def translate_file(path: Path, translate_line, offset: int = 0):
    """按字节偏移增量读一个 JSONL 文件，半行留到下次。

    translate_line(raw: dict, state: dict) -> list[dict] 由各插件提供。
    droid.py 内还有一份更早的同形实现；第三个插件落地后统一迁到这里。
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
    state = {"session_id": Path(path).stem}
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


def step_tail(root: Path, translate_file_fn, ledger, state: dict) -> list:
    """扫 root（目录递归或单文件），对 size 增长的 JSONL 增量翻译并追加账本。

    state: {str(path): offset}，调用方持久持有。返回本批事件（测试用）。
    """
    from ata.schema import parse_event
    root = Path(root)
    if root.is_dir():
        files = sorted(root.rglob("*.jsonl"))
    elif root.is_file():
        files = [root]
    else:
        return []
    batch = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size <= state.get(str(f), 0):
            continue
        events, new_offset = translate_file_fn(f, state.get(str(f), 0))
        for ev in events:
            ledger.append(parse_event(ev))
            batch.append(ev)
        state[str(f)] = new_offset
    return batch


def tail_path(path: Path, translate_file_fn, ledger):
    """1s 轮询：目录递归 / 单文件都支持，首轮即灌入已有文件（账本按 id 幂等）。"""
    state = {}
    while True:
        try:
            step_tail(path, translate_file_fn, ledger, state)
        except Exception:
            # 目录被删/权限抖动：下一轮再试，不拖死整个服务。
            pass
        time.sleep(1)
