import argparse
import threading
from pathlib import Path

from ata.http import make_server
from ata.ledger import Ledger
from ata.plugins.droid import translate_file
from ata.schema import parse_event


def seed_long(ledger: Ledger):
    ledger.append({
        "v": 1, "id": "o", "agent_id": "pi", "session_id": "pi-long",
        "ts": 1, "type": "session.opened", "turn": None, "payload": {"title": "long"},
    })
    for i in range(1, 121):
        role = "user" if i % 2 else "assistant"
        ledger.append({
            "v": 1, "id": f"m{i}", "agent_id": "pi", "session_id": "pi-long",
            "ts": i, "type": "message.upserted", "turn": (i + 1) // 2,
            "payload": {
                "message_id": f"m{i}", "role": role, "text": f"row {i}",
                "status": "completed", "request_no": None if role == "user" else i,
                "usage": None, "started_at": 1000 + i, "duration_ms": 10,
                "output_text": f"row {i}",
            },
        })


def seed_demo(ledger: Ledger):
    pi = [
        {"v":1,"id":"o","agent_id":"pi","session_id":"pi-compact","ts":1786694320000,"type":"session.opened","turn":None,"payload":{"title":"synthetic pi turn"}},
        {"v":1,"id":"t1s","agent_id":"pi","session_id":"pi-compact","ts":1786694320100,"type":"turn.started","turn":1,"payload":{}},
        {"v":1,"id":"u1","agent_id":"pi","session_id":"pi-compact","ts":1786694320200,"type":"message.upserted","turn":1,"payload":{"message_id":"u1","role":"user","text":"user asks to mark missing usage","status":"completed","request_no":None,"usage":None,"started_at":1786694320200,"duration_ms":40,"output_text":None}},
        {"v":1,"id":"a1","agent_id":"pi","session_id":"pi-compact","ts":1786694320380,"type":"message.upserted","turn":1,"payload":{"message_id":"a1","role":"assistant","text":"reported usage on this turn","status":"completed","request_no":1,"usage":{"status":"reported","input":1840,"output":612,"cache_read":220,"cache_write":48,"total_tokens":2720,"cost":None},"started_at":1786694320380,"duration_ms":920,"output_text":"reported usage on this turn"}},
        {"v":1,"id":"c1","agent_id":"pi","session_id":"pi-compact","ts":1786694321120,"type":"tool.upserted","turn":1,"payload":{"tool_call_id":"c1","parent_message_id":"a1","name":"Read","text":"ledger.md","status":"completed","payload":{"path":"ledger.md"},"result":"ok","started_at":1786694321120,"duration_ms":210}},
        {"v":1,"id":"t1e","agent_id":"pi","session_id":"pi-compact","ts":1786694321400,"type":"turn.ended","turn":1,"payload":{"usage":{"status":"reported","input":1840,"output":612,"cache_read":220,"cache_write":48,"total_tokens":2720,"cost":None}}},
        {"v":1,"id":"t2s","agent_id":"pi","session_id":"pi-compact","ts":1786694322280,"type":"turn.started","turn":2,"payload":{}},
        {"v":1,"id":"u2","agent_id":"pi","session_id":"pi-compact","ts":1786694322280,"type":"message.upserted","turn":2,"payload":{"message_id":"u2","role":"user","text":"do not amortize session totals","status":"completed","request_no":None,"usage":None,"started_at":1786694322280,"duration_ms":20,"output_text":None}},
        {"v":1,"id":"a2","agent_id":"pi","session_id":"pi-compact","ts":1786694322520,"type":"message.upserted","turn":2,"payload":{"message_id":"a2","role":"assistant","text":"second turn keeps reported usage","status":"completed","request_no":2,"usage":{"status":"reported","input":2104,"output":388,"cache_read":1800,"cache_write":64,"total_tokens":4356,"cost":None},"started_at":1786694322520,"duration_ms":1480,"output_text":"second turn keeps reported usage"}},
        {"v":1,"id":"c2","agent_id":"pi","session_id":"pi-compact","ts":1786694323120,"type":"tool.upserted","turn":2,"payload":{"tool_call_id":"c2","parent_message_id":"a2","name":"Grep","text":"pattern: cue","status":"completed","payload":{"pattern":"cue"},"result":"Found 1 match","started_at":1786694323120,"duration_ms":233}},
        {"v":1,"id":"c3","agent_id":"pi","session_id":"pi-compact","ts":1786694323640,"type":"tool.upserted","turn":2,"payload":{"tool_call_id":"c3","parent_message_id":"a2","name":"Read","text":"denied.md","status":"failed","payload":{"path":"denied.md"},"result":"EACCES","started_at":1786694323640,"duration_ms":210}},
        {"v":1,"id":"t2e","agent_id":"pi","session_id":"pi-compact","ts":1786694324000,"type":"turn.ended","turn":2,"payload":{"usage":{"status":"reported","input":2104,"output":388,"cache_read":1800,"cache_write":64,"total_tokens":4356,"cost":None}}},
    ]
    for ev in pi:
        ledger.append(parse_event(ev))
    evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
    for ev in evs:
        ledger.append(parse_event(ev))
    seed_long(ledger)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["serve", "seed"])
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--ledger", default="./data")
    p.add_argument("--web", default="web")
    p.add_argument("--droid-path")
    p.add_argument("--claude-path")
    p.add_argument("--codex-path")
    # 目录 tail 只处理最近 N 天修改的文件；厂商历史会话动辄几千个，全量灌入
    # 会让账本涨到数 GB。None/0 表示不做限制。
    p.add_argument("--tail-max-age-days", type=int, default=7)
    args = p.parse_args(argv)
    led = Ledger(Path(args.ledger))
    if args.cmd == "seed":
        seed_demo(led)
        print(f"seeded {led.path}")
        return
    # 目录/单文件统一走 tail_path：首轮灌入近期文件（账本按 id 幂等），
    # 之后 1s 轮询发现新文件与活动会话的追加行。显式传入才打开，默认不碰厂商目录。
    def start_tail(path_arg, tf):
        if not path_arg:
            return
        from ata.plugins.jsonl import tail_path
        threading.Thread(target=tail_path, args=(Path(path_arg), tf, led),
                         kwargs={"max_age_days": args.tail_max_age_days}, daemon=True).start()

    start_tail(args.droid_path, translate_file)
    if args.claude_path:
        from ata.plugins.claude import translate_file as claude_tf
        start_tail(args.claude_path, claude_tf)
    if args.codex_path:
        from ata.plugins.codex import translate_file as codex_tf
        start_tail(args.codex_path, codex_tf)
    httpd = make_server(led, Path(args.web), "127.0.0.1", args.port)
    print(f"atatrace http://127.0.0.1:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
