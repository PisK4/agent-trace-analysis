from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from ata.schema import envelope

DEFAULT_URL = "http://127.0.0.1:8787"
REGRESSION_DIR = Path.home() / ".ata" / "regression"
TASKS_FILE = REGRESSION_DIR / "tasks.jsonl"
RUNS_DIR = REGRESSION_DIR / "runs"
# 指标词表：客观过程信号 + 主观标注。最终清单由「指标清单定稿」票裁决后在此增删。
METRICS = ["human_score", "turns", "tool_fail_rate",
           "tokens_reported", "usage_missing_turns", "duration_s"]


def build_parser():
    p = argparse.ArgumentParser(prog="ata read")
    p.add_argument("what", choices=[
        "sessions", "events", "lineage", "usage", "tools", "compactions"])
    p.add_argument("sid", nargs="?", help="session id（sessions 子命令不需要）")
    p.add_argument("--agent")
    p.add_argument("--since-days", type=int)
    p.add_argument("--limit", type=int)
    p.add_argument("--after-seq", type=int)
    p.add_argument("--status", choices=["failed", "completed"])
    p.add_argument("--name")
    p.add_argument("--full", action="store_true")
    p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    p.add_argument("--ledger")
    return p


def _local(ledger_path, args):
    from ata.ledger import Ledger
    from ata.project import list_compactions, list_tools, summarize_usage
    led = Ledger(ledger_path)
    if args.what == "sessions":
        rows = led.sessions()
        if args.agent:
            rows = [r for r in rows if r["agent"] == args.agent]
        return {"ok": True, "sessions": rows}
    if not args.sid:
        sys.exit("error: sid required")
    if led.session(args.sid) is None:
        sys.exit('error: {"ok": false, "error": "unknown session"}')
    if args.what == "events":
        recs = [r for r in led.read(args.sid)
                if args.after_seq is None or r["seq"] > args.after_seq]
        if args.limit:
            recs = recs[: args.limit]
        return {"ok": True, "events": recs,
                "next_after_seq": recs[-1]["seq"] if recs else (args.after_seq or 0)}
    if args.what == "lineage":
        return {"ok": True, "ancestors": led.ancestry(args.sid),
                "children": led.children(args.sid)}
    if args.what == "usage":
        return {"ok": True, **summarize_usage(led.read(args.sid))}
    if args.what == "tools":
        rows = list_tools(led.read(args.sid), args.status, args.name)
        return {"ok": True, "tools": rows}
    return {"ok": True, "compactions": list_compactions(led.read(args.sid))}


def _remote(base, what, sid, args):
    q = []
    if getattr(args, "after_seq", None) is not None:
        q.append(f"after_seq={args.after_seq}")
    if getattr(args, "limit", None):
        q.append(f"limit={args.limit}")
    if getattr(args, "status", None):
        q.append(f"status={args.status}")
    if getattr(args, "name", None):
        q.append(f"name={args.name}")
    if getattr(args, "full", False):
        q.append("full=true")
    path = "/api/sessions" if what == "sessions" else f"/api/sessions/{sid}/{what}"
    url = base.rstrip("/") + path + ("?" + "&".join(q) if q else "")
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {e.read().decode()}")
    except urllib.error.URLError as e:
        sys.exit(f"error: service unreachable ({e.reason}); "
                 f"try --ledger ~/.ata/ata.sqlite")


def apply_client_filters(data, args):
    # 远端 /api/sessions 返回裸数组，归一化成与 --ledger 模式一致的形状
    if args.what == "sessions" and isinstance(data, list):
        data = {"ok": True, "sessions": data}
    if args.what == "sessions" and "sessions" in data:
        # /api/sessions 服务端不支持过滤参数，limit/agent 由客户端裁剪
        if args.agent:
            data["sessions"] = [r for r in data["sessions"] if r["agent"] == args.agent]
        if args.limit:
            data["sessions"] = data["sessions"][: args.limit]
    return data


def main(argv):
    if argv and argv[0] == "rate":
        return _rate_main(argv)
    if argv and argv[0] == "tasks":
        return _tasks_main(argv)
    if argv and argv[0] == "run":
        return _run_main(argv)
    if argv and argv[0] == "compare":
        return _compare_main(argv)
    args = build_parser().parse_args(argv[1:] if argv and argv[0] == "read" else argv)
    if args.ledger:
        data = _local(args.ledger, args)
    else:
        data = apply_client_filters(_remote(args.url, args.what, args.sid, args), args)
    print(json.dumps(data, ensure_ascii=False))


def _rate_main(argv):
    # 「标注」专指人类来源的主观真值（T9）；机器检测的失败信号是另一路，
    # 不得复用 session.scored 的「标注」称谓。词汇定义见仓库根 CONTEXT.md。
    p = argparse.ArgumentParser(prog="ata rate")
    p.add_argument("sid")
    p.add_argument("--value", required=True, choices=["good", "bad", "partial"])
    p.add_argument("--note")
    p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    p.add_argument("--ledger")
    a = p.parse_args(argv[1:])
    if a.ledger:
        sys.exit("error: rate 是写操作，只能走服务（去掉 --ledger）")
    meta = _remote(a.url, "sessions", None, argparse.Namespace(
        what="sessions", sid=None, after_seq=None, limit=None,
        status=None, name=None, full=False))
    if isinstance(meta, list):  # 远端 /api/sessions 返回裸数组
        meta = {"ok": True, "sessions": meta}
    mine = next((r for r in meta.get("sessions", []) if r["id"] == a.sid), None)
    agent = mine["agent"] if mine else "pi"
    ev = build_score_event(agent, a.sid, a.value, a.note)
    result = post_json(a.url, "/api/events", {"events": [ev]})
    print(json.dumps(result, ensure_ascii=False))


def build_score_event(agent_id, session_id, value, note=None):
    payload = {"value": value}
    if note:
        payload["note"] = note
    return envelope(agent_id, session_id, "session.scored", payload)


def post_json(base, path, body):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def get_json(base, path):
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {e.read().decode()}")
    except urllib.error.URLError as e:
        sys.exit(f"error: service unreachable ({e.reason}); try --ledger for read-only ops")


# ---- 回归任务集与实验轮次（T5 决议：文件放 ~/.ata/regression/，本地 git 管版本）----

def _tasks_main(argv):
    p = argparse.ArgumentParser(prog="ata tasks")
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="追加一道题（题面从 stdin 贴入）")
    add.add_argument("--channel", required=True,
                     help="重跑时用哪个宿主（cue/pi/droid/claude/codex）")
    add.add_argument("--model")
    add.add_argument("--thinking-level")
    add.add_argument("--k", type=int, default=1,
                     help="独立重跑次数，pass^k 用；默认 1")
    add.add_argument("--taskset", type=Path, default=TASKS_FILE)
    lst = sub.add_parser("list", help="列出全部题目")
    lst.add_argument("--taskset", type=Path, default=TASKS_FILE)
    a = p.parse_args(argv[1:])
    if a.cmd == "add":
        text = sys.stdin.read().strip()
        if not text:
            sys.exit("error: 题面为空；把首条用户消息原文从 stdin 贴入")
        task = {"task_id": "t-" + uuid.uuid4().hex[:8], "input": text,
                "channel": a.channel, "model": a.model,
                "thinking_level": a.thinking_level, "k": a.k}
        a.taskset.parent.mkdir(parents=True, exist_ok=True)
        with a.taskset.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
        print(json.dumps({"ok": True, "task_id": task["task_id"],
                          "taskset": str(a.taskset)}, ensure_ascii=False))
    else:
        rows = []
        if a.taskset.exists():
            for line in a.taskset.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        print(json.dumps({"ok": True, "tasks": rows}, ensure_ascii=False))


def _run_main(argv):
    p = argparse.ArgumentParser(prog="ata run")
    sub = p.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new", help="创建一轮实验（干预后先建 run 再重跑）")
    new.add_argument("--desc", required=True, help="这轮改了什么，一句话")
    new.add_argument("--taskset", type=Path, default=TASKS_FILE)
    new.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    lst = sub.add_parser("list", help="列出现有轮次")
    lst.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    a = p.parse_args(argv[1:])
    if a.cmd == "new":
        fp = (hashlib.sha256(a.taskset.read_bytes()).hexdigest()[:16]
              if a.taskset.exists() else None)
        result = post_json(a.url, "/api/runs",
                           {"description": a.desc, "taskset_fingerprint": fp})
    else:
        result = get_json(a.url, "/api/runs")
    print(json.dumps(result, ensure_ascii=False))


def collect_task_score(proj):
    """投影 → 单会话的 score 记录。缺数据记 None（missing），永不当作 0。"""
    rows = proj.get("rows", [])
    tools = [r for r in rows if r.get("kind") == "tool"]
    fails = sum(1 for r in tools if r.get("status") == "failed")
    asst = [r for r in rows if r.get("kind") == "assistant"]
    reported = [r["usage"]["totalTokens"] for r in asst
                if (r.get("usage") or {}).get("status") == "reported"
                and r["usage"].get("totalTokens") is not None]
    missing = sum(1 for r in asst
                  if (r.get("usage") or {}).get("status") != "reported")
    scores = proj.get("scores") or []
    starts = [r["startedAt"] for r in rows if r.get("startedAt")]
    ends = [(r.get("startedAt") or 0) + (r.get("durationMs") or 0)
            for r in rows if r.get("startedAt")]
    duration = round((max(ends) - min(starts)) / 1000, 1) if len(starts) > 1 else None
    return [
        {"name": "human_score", "value": scores[-1]["value"] if scores else None,
         "type": "categorical", "source": "human"},
        {"name": "turns", "value": proj.get("turns"), "type": "number", "source": "machine"},
        {"name": "tool_fail_rate",
         "value": round(fails / len(tools), 4) if tools else None,
         "type": "number", "source": "machine"},
        {"name": "tokens_reported", "value": sum(reported) if reported else None,
         "type": "number", "source": "machine"},
        {"name": "usage_missing_turns", "value": missing if asst else None,
         "type": "number", "source": "machine"},
        {"name": "duration_s", "value": duration, "type": "number", "source": "machine"},
    ]


def _latest_by_task(assignments):
    # 同一任务重跑归组多次时取最新一条
    m = {}
    for a in assignments:
        m[a["task_id"]] = a["session_id"]
    return m


def _write_snapshot(run_id, per_task):
    d = RUNS_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "scores.jsonl").open("w", encoding="utf-8") as f:
        for task_id, (sid, recs) in sorted(per_task.items()):
            for rec in recs:
                f.write(json.dumps({"task_id": task_id, "session_id": sid, **rec},
                                   ensure_ascii=False) + "\n")


def _cell(per_task, task_id, name):
    for rec in per_task.get(task_id, ([], []))[1]:
        if rec["name"] == name:
            return rec["value"]
    return None


def _delta(x, y):
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return f"{y - x:+g}"
    return "n/a"  # 任一侧 missing 不算差值


def _compare_main(argv):
    p = argparse.ArgumentParser(prog="ata compare")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    a = p.parse_args(argv[1:])
    base = a.url.rstrip("/")
    ra = get_json(base, f"/api/runs/{a.run_a}")
    rb = get_json(base, f"/api/runs/{a.run_b}")

    def fetch_scores(run):
        out = {}
        for task_id, sid in _latest_by_task(run["assignments"]).items():
            out[task_id] = (sid, collect_task_score(get_json(base, f"/api/sessions/{sid}")))
        return out

    sa, sb = fetch_scores(ra), fetch_scores(rb)
    _write_snapshot(a.run_a, sa)
    _write_snapshot(a.run_b, sb)

    lines = [
        f"# compare {a.run_a} vs {a.run_b}",
        f"- A: {ra['description']}（任务集 {ra.get('taskset_fingerprint')}）",
        f"- B: {rb['description']}（任务集 {rb.get('taskset_fingerprint')}）",
        "- 同版任务集才可比；miss 表示数据缺失，n/a 表示差值不可算。",
        "",
    ]
    header = "| task | " + " | ".join(f"{m} A | {m} B | Δ{m}" for m in METRICS) + " |"
    lines += [header, "|" + "---|" * (len(METRICS) * 3 + 1)]
    for t in sorted(set(sa) | set(sb)):
        cells = []
        for m in METRICS:
            x, y = _cell(sa, t, m), _cell(sb, t, m)
            cells += ["miss" if v is None else str(v) for v in (x, y)] + [_delta(x, y)]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    print("\n".join(lines))
