from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8787"


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
    if args.what == "sessions" and args.agent and "sessions" in data:
        data["sessions"] = [r for r in data["sessions"] if r["agent"] == args.agent]
    return data


def main(argv):
    if argv and argv[0] == "rate":
        return _rate_main(argv)
    args = build_parser().parse_args(argv[1:] if argv and argv[0] == "read" else argv)
    if args.ledger:
        data = _local(args.ledger, args)
    else:
        data = apply_client_filters(_remote(args.url, args.what, args.sid, args), args)
    print(json.dumps(data, ensure_ascii=False))


def _rate_main(argv):
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
    mine = next((r for r in meta.get("sessions", []) if r["id"] == a.sid), None)
    agent = mine["agent"] if mine else "pi"
    ev = build_score_event(agent, a.sid, a.value, a.note)
    result = post_json(a.url, "/api/events", {"events": [ev]})
    print(json.dumps(result, ensure_ascii=False))


def build_score_event(agent_id, session_id, value, note=None):
    payload = {"value": value}
    if note:
        payload["note"] = note
    return {"v": 1, "id": uuid.uuid4().hex, "agent_id": agent_id,
            "session_id": str(session_id), "ts": int(time.time() * 1000),
            "type": "session.scored", "turn": None, "payload": payload}


def post_json(base, path, body):
    req = urllib.request.Request(
        base.rstrip("/") + path, data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)
