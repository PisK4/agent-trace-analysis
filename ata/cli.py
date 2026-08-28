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
CLI_SUBCOMMANDS = {"read", "rate"}


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
    from ata.queries import list_compactions, list_tools, summarize_usage
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
