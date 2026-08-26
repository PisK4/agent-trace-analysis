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

# CLI 子命令集合的唯一归属地：__main__ 据此把机器读路径分发进本模块，
# 两处各写一遍会漂移（架构评审二轮候选 7）。
CLI_SUBCOMMANDS = {"read", "rate", "tasks", "run", "compare"}


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


def _request(base, path, body=None):
    """CLI 统一 HTTP 通道（架构评审二轮候选 7）：错误纪律与超时只有一份。
    CLI 是短命进程，失败直接退出，没有重试语义可谈。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data,
        headers={"content-type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"error: {e.read().decode()}")
    except urllib.error.URLError as e:
        sys.exit(f"error: service unreachable ({e.reason}); "
                 f"try --ledger ~/.ata/ata.sqlite for read-only ops")


def _remote(base, what, sid, filters):
    """filters: {after_seq, limit, status, name, full}——调用方从各自 args 提取，
    本函数不再依赖 argparse.Namespace 的形状（假 Namespace 七个 None 的骗局已拆）。"""
    q = []
    if filters.get("after_seq") is not None:
        q.append(f"after_seq={filters['after_seq']}")
    if filters.get("limit"):
        q.append(f"limit={filters['limit']}")
    if filters.get("status"):
        q.append(f"status={filters['status']}")
    if filters.get("name"):
        q.append(f"name={filters['name']}")
    if filters.get("full"):
        q.append("full=true")
    path = "/api/sessions" if what == "sessions" else f"/api/sessions/{sid}/{what}"
    return _request(base, path + ("?" + "&".join(q) if q else ""))


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
        filters = {k: getattr(args, k, None)
                   for k in ("after_seq", "limit", "status", "name", "full")}
        data = apply_client_filters(_remote(args.url, args.what, args.sid, filters), args)
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
    meta = _remote(a.url, "sessions", None, {})
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
    return _request(base, path, body)


def get_json(base, path):
    return _request(base, path)


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


def collect_task_score(usage_resp, tools_resp, timing_resp, human_score, turns):
    """便捷层响应 → 单会话 score 记录。缺数据记 None（missing），永不当作 0。

    口径全部来自便捷层（spec 定稿端点）：fail_rate 出 /tools，tokens 出
    /usage 逐轮 reported 合计，duration 出 /timing 的 span_ms（占位排除
    已在其内部完成）。compare 不再自己重推一遍平行口径。
    """
    tools = tools_resp.get("tools") or []
    fails = sum(1 for t in tools if t.get("status") == "failed")
    turn_rows = usage_resp.get("turns") or []
    reported = [r.get("total_tokens") for r in turn_rows
                if r.get("status") == "reported" and r.get("total_tokens") is not None]
    span_ms = timing_resp.get("span_ms")
    return [
        {"name": "human_score", "value": human_score,
         "type": "categorical", "source": "human"},
        {"name": "turns", "value": turns, "type": "number", "source": "machine"},
        {"name": "tool_fail_rate",
         "value": round(fails / len(tools), 4) if tools else None,
         "type": "number", "source": "machine"},
        {"name": "tokens_reported", "value": sum(reported) if reported else None,
         "type": "number", "source": "machine"},
        {"name": "usage_missing_turns",
         "value": usage_resp.get("missing_turns") if turn_rows else None,
         "type": "number", "source": "machine"},
        {"name": "duration_s",
         "value": round(span_ms / 1000, 1) if isinstance(span_ms, (int, float)) and span_ms > 0 else None,
         "type": "number", "source": "machine"},
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
        base_path = "/api/sessions"
        out = {}
        for task_id, sid in _latest_by_task(run["assignments"]).items():
            usage = get_json(base, f"{base_path}/{sid}/usage")
            tools = get_json(base, f"{base_path}/{sid}/tools")
            timing = get_json(base, f"{base_path}/{sid}/timing")
            proj = get_json(base, f"{base_path}/{sid}")
            score_events = proj.get("scores") or []
            human = score_events[-1]["value"] if score_events else None
            out[task_id] = (sid, collect_task_score(
                usage, tools, timing, human, proj.get("turns")))
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
