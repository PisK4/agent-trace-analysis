from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from ata.schema import envelope

DEFAULT_URL = "http://127.0.0.1:17877"
# CLI 子命令集合的唯一归属地：__main__ 据此把机器读路径分发进本模块，
# 两处各写一遍会漂移（架构评审二轮候选 7）。
CLI_SUBCOMMANDS = {"read", "rate", "evaluation", "evaluations", "eval"}


def build_parser():
    p = argparse.ArgumentParser(prog="ata read")
    p.add_argument("what", choices=[
        "sessions", "runs", "turns", "events", "lineage", "usage", "tools", "compactions"])
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
    from ata.queries import list_compactions, list_tools, summarize_usage, list_runs, list_turns
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
    if args.what == "runs":
        return {"ok": True, "runs": list_runs(led, args.sid)}
    if args.what == "turns":
        return {"ok": True, "turns": list_turns(led, args.sid)}
    if args.what == "lineage":
        return {"ok": True, "ancestors": led.ancestry(args.sid),
                "children": led.children(args.sid)}
    if args.what == "usage":
        return {"ok": True, **summarize_usage(led.read(args.sid))}
    if args.what == "tools":
        rows = list_tools(led.read(args.sid), args.status, args.name)
        return {"ok": True, "tools": rows}
    return {"ok": True, "compactions": list_compactions(led.read(args.sid))}


def _request(base, path, body=None, method=None):
    """CLI 统一 HTTP 通道；错误纪律与超时只有一份。"""
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data,
        headers={"content-type": "application/json"} if data is not None else {},
        method=method or ("POST" if data is not None else "GET"))
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
    if argv and argv[0] in {"evaluation", "evaluations", "eval"}:
        return _evaluation_main(argv)
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
    if mine is None:
        sys.exit('error: {"ok": false, "error": "unknown session"}')
    ev = build_score_event(mine["agent"], a.sid, a.value, a.note)
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


def _evaluation_main(argv):
    """Evaluation 的 CRUD、membership 与 history 命令统一走 HTTP facade。"""
    p = argparse.ArgumentParser(prog="ata evaluation")
    p.add_argument("--url", default=os.environ.get("ATA_URL") or DEFAULT_URL)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", aliases=["ls"])
    create = sub.add_parser("create", aliases=["new"])
    create.add_argument("title", nargs="?")
    create.add_argument("--title", dest="title_opt")
    show = sub.add_parser("show", aliases=["get"])
    show.add_argument("evaluation_id")
    hist = sub.add_parser("history", aliases=["events"])
    hist.add_argument("evaluation_id")
    rename = sub.add_parser("rename")
    rename.add_argument("evaluation_id")
    rename.add_argument("title", nargs="?")
    rename.add_argument("--title", dest="title_opt")
    delete = sub.add_parser("delete", aliases=["remove"])
    delete.add_argument("evaluation_id")
    add = sub.add_parser("add", aliases=["add-session", "member"])
    add.add_argument("evaluation_id")
    add.add_argument("session_id")
    add.add_argument("--task-label", default="")
    remove = sub.add_parser("remove-session", aliases=["remove-member", "rm", "rm-session"])
    remove.add_argument("evaluation_id")
    remove.add_argument("session_id")
    a = p.parse_args(argv[1:])
    base = a.url.rstrip("/")
    cmd = a.cmd
    if cmd in {"list", "ls"}:
        result = get_json(base, "/api/evaluations")
    elif cmd in {"create", "new"}:
        title = (a.title_opt if a.title_opt is not None else a.title or "").strip()
        if not title:
            p.error("create requires title")
        result = post_json(base, "/api/evaluations", {"title": title})
    elif cmd in {"show", "get"}:
        result = get_json(base, f"/api/evaluations/{a.evaluation_id}")
    elif cmd in {"history", "events"}:
        result = get_json(base, f"/api/evaluations/{a.evaluation_id}/history")
    elif cmd == "rename":
        title = (a.title_opt if a.title_opt is not None else a.title or "").strip()
        if not title:
            p.error("rename requires title")
        result = _request(base, f"/api/evaluations/{a.evaluation_id}", {"title": title}, "PATCH")
    elif cmd in {"delete", "remove"}:
        result = _request(base, f"/api/evaluations/{a.evaluation_id}", method="DELETE")
    elif cmd in {"add", "add-session", "member"}:
        result = post_json(base, f"/api/evaluations/{a.evaluation_id}/sessions",
                           {"session_id": a.session_id, "task_label": a.task_label})
    else:
        result = _request(base, f"/api/evaluations/{a.evaluation_id}/sessions/{a.session_id}", method="DELETE")
    print(json.dumps(result, ensure_ascii=False))
