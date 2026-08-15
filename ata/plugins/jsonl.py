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
    data = Path(path).read_bytes()
    chunk = data[offset:]
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
        raw = json.loads(line)
        events.extend(translate_line(raw, state))
    return events, new_offset


def tail_forever(path: Path, translate_file_fn, ledger):
    """1s 轮询追加：translate_file_fn(path, offset) -> (events, new_offset)。"""
    from ata.schema import parse_event
    offset = 0
    while True:
        events, offset = translate_file_fn(path, offset)
        for ev in events:
            ledger.append(parse_event(ev))
        time.sleep(1)
