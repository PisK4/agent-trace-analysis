import argparse
import sys
from pathlib import Path

from ata.ingest import start_tails
from ata.http import make_server
from ata.ledger import Ledger
from ata.cli import CLI_SUBCOMMANDS
from ata.plugins.droid import translate_file
from ata.schema import parse_event


def seed_long(ledger: Ledger):
    ledger.append({
        "v": 1, "id": "o", "agent_id": "pi", "session_id": "pi-long",
        "ts": 1, "type": "session.opened", "run_id": None, "turn_number": None, "observed_turn_ordinal": None, "payload": {"title": "long"},
    })
    for i in range(1, 121):
        role = "user" if i % 2 else "assistant"
        ledger.append({
            "v": 1, "id": f"m{i}", "agent_id": "pi", "session_id": "pi-long",
            "ts": i, "type": "message.upserted", "run_id": None, "turn_number": None, "observed_turn_ordinal": (i + 1) // 2,
            "payload": {
                "message_id": f"m{i}", "role": role, "text": f"row {i}",
                "status": "completed", "request_no": None if role == "user" else i,
                "usage": None, "started_at": 1000 + i, "duration_ms": 10,
                "output_text": f"row {i}",
            },
        })


def seed_demo(ledger: Ledger):
    pi = [
        {"v":1,"id":"o","agent_id":"pi","session_id":"pi-compact","ts":1786694320000,"type":"session.opened","run_id":None,"turn_number":None,"observed_turn_ordinal":None,"payload":{"title":"synthetic pi turn"}},
        {"v":1,"id":"t1s","agent_id":"pi","session_id":"pi-compact","ts":1786694320100,"type":"turn.started","run_id":None,"turn_number":None,"observed_turn_ordinal":1,"payload":{}},
        {"v":1,"id":"u1","agent_id":"pi","session_id":"pi-compact","ts":1786694320200,"type":"message.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":1,"payload":{"message_id":"u1","role":"user","text":"user asks to mark missing usage","status":"completed","request_no":None,"usage":None,"started_at":1786694320200,"duration_ms":40,"output_text":None}},
        {"v":1,"id":"a1","agent_id":"pi","session_id":"pi-compact","ts":1786694320380,"type":"message.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":1,"payload":{"message_id":"a1","role":"assistant","text":"reported usage on this turn","status":"completed","request_no":1,"usage":{"status":"reported","input":1840,"output":612,"cache_read":220,"cache_write":48,"total_tokens":2720,"cost":None},"started_at":1786694320380,"duration_ms":920,"output_text":"reported usage on this turn"}},
        {"v":1,"id":"c1","agent_id":"pi","session_id":"pi-compact","ts":1786694321120,"type":"tool.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":1,"payload":{"tool_call_id":"c1","parent_message_id":"a1","name":"Read","text":"ledger.md","status":"completed","payload":{"path":"ledger.md"},"result":"ok","started_at":1786694321120,"duration_ms":210}},
        {"v":1,"id":"t1e","agent_id":"pi","session_id":"pi-compact","ts":1786694321400,"type":"turn.ended","run_id":None,"turn_number":None,"observed_turn_ordinal":1,"payload":{"usage":{"status":"reported","input":1840,"output":612,"cache_read":220,"cache_write":48,"total_tokens":2720,"cost":None}}},
        {"v":1,"id":"t2s","agent_id":"pi","session_id":"pi-compact","ts":1786694322280,"type":"turn.started","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{}},
        {"v":1,"id":"u2","agent_id":"pi","session_id":"pi-compact","ts":1786694322280,"type":"message.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{"message_id":"u2","role":"user","text":"do not amortize session totals","status":"completed","request_no":None,"usage":None,"started_at":1786694322280,"duration_ms":20,"output_text":None}},
        {"v":1,"id":"a2","agent_id":"pi","session_id":"pi-compact","ts":1786694322520,"type":"message.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{"message_id":"a2","role":"assistant","text":"second turn keeps reported usage","status":"completed","request_no":2,"usage":{"status":"reported","input":2104,"output":388,"cache_read":1800,"cache_write":64,"total_tokens":4356,"cost":None},"started_at":1786694322520,"duration_ms":1480,"output_text":"second turn keeps reported usage"}},
        {"v":1,"id":"c2","agent_id":"pi","session_id":"pi-compact","ts":1786694323120,"type":"tool.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{"tool_call_id":"c2","parent_message_id":"a2","name":"Grep","text":"pattern: cue","status":"completed","payload":{"pattern":"cue"},"result":"Found 1 match","started_at":1786694323120,"duration_ms":233}},
        {"v":1,"id":"c3","agent_id":"pi","session_id":"pi-compact","ts":1786694323640,"type":"tool.upserted","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{"tool_call_id":"c3","parent_message_id":"a2","name":"Read","text":"denied.md","status":"failed","payload":{"path":"denied.md"},"result":"EACCES","started_at":1786694323640,"duration_ms":210}},
        {"v":1,"id":"t2e","agent_id":"pi","session_id":"pi-compact","ts":1786694324000,"type":"turn.ended","run_id":None,"turn_number":None,"observed_turn_ordinal":2,"payload":{"usage":{"status":"reported","input":2104,"output":388,"cache_read":1800,"cache_write":64,"total_tokens":4356,"cost":None}}},
    ]
    for ev in pi:
        ledger.append(parse_event(ev))
    evs, _ = translate_file(Path("testdata/vendor/droid-sample.jsonl"))
    for ev in evs:
        ledger.append(parse_event(ev))
    seed_long(ledger)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # 机器读路径与 Evaluation CRUD 都分发进 CLI 模块；集合唯一归属地在 ata.cli.CLI_SUBCOMMANDS。
    # 这样 serve/seed 保留进程入口，evaluation 不在这里重复解析参数。
    if argv and argv[0] in CLI_SUBCOMMANDS:
        from ata.cli import main as cli_main
        return cli_main(argv)
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["serve", "seed"])
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--ledger", default="./data")
    p.add_argument("--web", default="web/dist")
    p.add_argument("--droid-path")
    p.add_argument("--claude-path")
    p.add_argument("--codex-path")
    # 目录 tail 只处理最近 N 天修改的文件；厂商历史会话动辄几千个，全量灌入
    # 会让账本涨到数 GB。None/0 表示不做限制。
    p.add_argument("--tail-max-age-days", type=int, default=7)
    # 代理采集通道：默认关。开起来后把 agent 的 API base 指到这里即可补采。
    p.add_argument("--proxy-port", type=int, default=None)
    p.add_argument("--proxy-upstream", default="https://api.anthropic.com")
    p.add_argument("--proxy-agent", choices=["claude"], default="claude")
    args = p.parse_args(argv)
    led = Ledger(Path(args.ledger))
    if args.cmd == "seed":
        seed_demo(led)
        print(f"seeded {led.path}")
        return
    start_tails(
        led,
        tail_max_age_days=args.tail_max_age_days,
        droid_path=args.droid_path,
        claude_path=args.claude_path,
        codex_path=args.codex_path,
    )
    if args.proxy_port:
        import threading

        from ata.capture_proxy import start_capture_proxy
        from ata.plugins.capture import ingest_capture
        proxy_httpd = start_capture_proxy(
            "127.0.0.1", args.proxy_port, args.proxy_upstream, args.proxy_agent,
            lambda rec: ingest_capture(led, rec))
        threading.Thread(target=proxy_httpd.serve_forever, daemon=True).start()
        print(f"capture proxy http://127.0.0.1:{args.proxy_port} -> {args.proxy_upstream}")
    httpd = make_server(led, Path(args.web), "127.0.0.1", args.port)
    print(f"atatrace http://127.0.0.1:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
