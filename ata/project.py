import json

from ata.fold import fold_session_meta
from ata.plugins.common import PLACEHOLDER_MS, is_context_text

NA = {
    "status": "n/a", "input": None, "output": None,
    "cacheRead": None, "cacheWrite": None, "totalTokens": None, "cost": None,
}
MISS = {
    "status": "missing", "input": None, "output": None,
    "cacheRead": None, "cacheWrite": None, "totalTokens": None, "cost": None,
}


def _usage(raw):
    if not raw:
        return None
    if raw["status"] != "reported":
        return dict(MISS)
    return {
        "status": "reported",
        "input": raw["input"],
        "output": raw["output"],
        "cacheRead": raw["cache_read"],
        "cacheWrite": raw["cache_write"],
        "totalTokens": raw.get("total_tokens"),
        "cost": raw.get("cost"),
    }


def _esc(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _message_kind(p):
    if p.get("role") != "user":
        return p["role"], p["role"].upper()
    if is_context_text(p.get("text")):
        return "context", "CONTEXT"
    return "user", "USER"


def _tool_preview(name, payload, fallback=""):
    # dsh 工具行：`name {json}`，不把结果拼进主表。payload 空时回退到适配器摘要。
    if isinstance(payload, dict) and payload:
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            body = fallback or ""
        return f"{name} {body}" if body else name
    if fallback and fallback != name:
        return f"{name} {fallback}"
    return name or fallback


def project_session(session_id, agent, recs, *, tail=None, before=None):
    # 标题折叠与账本索引同吃 fold_session_meta（唯一规则归属地）：用户改名后
    # 后到的 opened 只做兜底不再覆盖。此前投影侧缺守卫，droid 的标题补写
    # opened 晚于用户改名时详情页会把标题打回自动名。
    meta_folded = None
    entities = {}
    order = []
    scores = []
    turn_usage = {}
    turn_status = {}
    turn_model = {}
    last_catalog = []
    last_skills = []
    for rec in recs:
        ev = rec["event"]
        seq = rec["seq"]
        p = ev["payload"]
        if ev["type"] in ("session.opened", "session.renamed"):
            meta_folded = fold_session_meta(meta_folded, ev)
            continue
        if ev["type"] == "session.scored":
            scores.append({"value": p.get("value"), "note": p.get("note"), "ts": ev["ts"]})
            continue
        if ev["type"] == "turn.ended":
            if p.get("usage"):
                turn_usage[ev["turn"]] = _usage(p["usage"])
            if p.get("status") in {"failed", "cancelled"}:
                turn_status[ev["turn"]] = p["status"]
            continue
        if ev["type"] == "message.upserted":
            # hook 执行记录等空正文 user 行（droid 修复前的存量脏数据）不进投影。
            if p["role"] == "user" and not p["text"]:
                continue
            key = ("m", p["message_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            kind, tag = _message_kind(p)
            model = p.get("model")
            effort = p.get("effort")
            if kind == "assistant" and model and ev.get("turn") is not None:
                turn_model[ev["turn"]] = {"model": model, "effort": effort}
            row.update({
                "id": p["message_id"],
                "_seq": seq,
                "turn": ev["turn"],
                "kind": kind,
                "tag": tag,
                "text": p["text"],
                "startedAt": p["started_at"],
                "durationMs": p.get("duration_ms") or 0,
                "status": p["status"],
                "requestNo": p.get("request_no"),
                "outputText": p.get("output_text"),
                "payloadText": p["text"] if p["role"] == "user" else None,
                "thinking": p.get("thinking"),
                "model": model,
                "effort": effort,
                "usage": _usage(p.get("usage")) if p["role"] == "assistant" else dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)
        elif ev["type"] == "tool.upserted":
            key = ("t", p["tool_call_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": p["tool_call_id"],
                "_seq": seq,
                "turn": ev["turn"],
                "kind": "tool",
                "tag": "TOOL",
                "name": p["name"],
                "text": _tool_preview(p.get("name") or "tool", p.get("payload"), p.get("text") or ""),
                "startedAt": p["started_at"],
                "durationMs": p.get("duration_ms") or 0,
                "status": p["status"],
                "parentId": p.get("parent_message_id"),
                "payload": p.get("payload"),
                "result": p.get("result"),
                "usage": dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)
        elif ev["type"] == "compaction.boundary":
            key = ("c", ev["id"])
            pre = p.get("pre_tokens")
            post = p.get("post_tokens")
            trigger = p.get("trigger")
            note_bits = []
            if trigger:
                note_bits.append(str(trigger))
            if pre is not None and post is not None:
                note_bits.append(f"{pre} → {post} tokens")
            elif p.get("removed_count") is not None:
                note_bits.append(f"removed {p['removed_count']}")
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": ev["id"],
                "_seq": seq,
                "turn": ev.get("turn"),
                "kind": "compacted",
                "tag": "COMPACTED",
                "text": p.get("summary") or "Context compacted",
                "startedAt": ev["ts"],
                "durationMs": p.get("duration_ms") or 0,
                "status": "completed",
                "note": " · ".join(note_bits) or None,
                "outputText": p.get("raw") or p.get("summary"),
                "usage": dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)
        elif ev["type"] == "system.upserted":
            key = ("s", ev["id"])
            # 目录按内容哈希去重落库，缺省轮次沿用最近一份（前向填充）。
            if p.get("tools_catalog") is not None:
                last_catalog = p["tools_catalog"]
            if p.get("skills_catalog") is not None:
                last_skills = p["skills_catalog"]
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": ev["id"],
                "_seq": seq,
                "turn": None,
                "kind": "system",
                "tag": "SYSTEM",
                "text": (p.get("prompt_text") or "")[:120],
                "startedAt": ev["ts"],
                "durationMs": 0,
                "status": "completed",
                "promptText": p.get("prompt_text"),
                "previousPrompt": p.get("previous_prompt"),
                "toolsCatalog": last_catalog,
                "skillsCatalog": last_skills,
                "usage": dict(NA),
            })
            entities[key] = row
            if key not in order:
                order.append(key)

    rows = [entities[k] for k in sorted(order, key=lambda k: entities[k]["_first"])]
    # 工具目录索引：按名字合并会话里全部 system.upserted 的 tools_catalog，
    # 后写覆盖前写，供前端按工具名查 Schema（dsh 的 Schema 页签同款取数）。
    tools_index = {}
    for row in rows:
        for tool in row.get("toolsCatalog") or []:
            if isinstance(tool, dict) and tool.get("name"):
                tools_index[str(tool["name"])] = tool
    # 已入库的 CONTEXT 仍可能带着适配器按 user 递增的 turn。
    # 投影时把这类孤儿轮次并回上一条真实用户轮次，避免 T2/T3 落在 reminder 上。
    last_user_turn = None
    remap = {}
    for row in rows:
        if row["kind"] == "user" and row.get("turn") is not None:
            last_user_turn = row["turn"]
        elif row["kind"] == "context" and last_user_turn is not None:
            if row.get("turn") != last_user_turn:
                remap[row["turn"]] = last_user_turn
            row["turn"] = last_user_turn
        elif row.get("turn") in remap:
            row["turn"] = remap[row["turn"]]

    seen_turn = set()
    for row in rows:
        if row["kind"] == "assistant":
            meta = turn_model.get(row.get("turn")) or {}
            if not row.get("model") and meta.get("model"):
                row["model"] = meta["model"]
                row["effort"] = meta.get("effort")
            ended = turn_status.get(row.get("turn"))
            if ended and row.get("status") == "completed":
                row["status"] = ended
        if row["kind"] in {"context", "system", "compacted"} or row["turn"] is None:
            row["start"] = False
            continue
        if row["turn"] not in seen_turn:
            row["start"] = True
            seen_turn.add(row["turn"])
        else:
            row["start"] = False

    step = 0
    for row in rows:
        # step 是「本轮第几次请求」，轮次边界重置；system 行（turn 为 null）不重置。
        if row["start"] and row["turn"] is not None:
            step = 0
        if row["kind"] == "assistant":
            step += 1
            row["step"] = step
            row["group"] = f"Step {step}"
            if (not row.get("usage") or row["usage"]["status"] != "reported") and row["turn"] in turn_usage:
                row["usage"] = turn_usage[row["turn"]] or dict(MISS)
            if row.get("usage") is None:
                row["usage"] = dict(MISS)
        else:
            row["step"] = step
            if step:
                row["group"] = f"Step {step}"

    has_older = False
    cursor = rows[0]["_seq"] if rows else 0
    if before is not None:
        rows = [r for r in rows if r["_seq"] < before]
        if tail:
            has_older = len(rows) > tail
            rows = rows[-tail:]
    elif tail:
        has_older = len(rows) > tail
        rows = rows[-tail:]
    if rows:
        cursor = rows[0]["_seq"]
    for i, row in enumerate(rows):
        row["index"] = i
    title = meta_folded["title"] if meta_folded else session_id
    return {
        "id": session_id,
        "agent": agent,
        "title": title,
        # 标题可能来自用户消息原文，crumb 走 innerHTML，必须转义。
        "crumb": f"{agent} · <b>{_esc(title)}</b>",
        "has_older": has_older,
        "cursor": cursor,
        "turns": len({t for t in seen_turn if t is not None}),
        "scores": scores,
        "tools_index": tools_index,
        "rows": rows,
    }


def tail_preview(text, n=200):
    if not isinstance(text, str) or len(text) <= n:
        return text
    return "…" + text[-n:]


def _usage_turns(recs):
    """逐轮 usage 行 + 压缩轮集合 + 最大轮号。summarize 与 audit 共用同一份推导，
    避免两处各推一遍日后漂移。行内带 seq，供前端从曲线跳回轨迹现场。
    context 是方言感知的上下文占用口径：Anthropic 系（claude）的 input 不含
    缓存部分，要加回 cache_read/cache_write 才是当轮真实上下文；codex/pi 的
    input 本身就是全量 prompt，直接用。"""
    turn_rows = {}
    turn_fallback = {}
    compaction_turns = set()
    max_turn = 0
    for rec in recs:
        e = rec["event"]
        p = e["payload"]
        if e.get("turn") is not None and e["turn"] > max_turn:
            max_turn = e["turn"]
        if e["type"] == "compaction.boundary":
            if e.get("turn") is not None:
                compaction_turns.add(e["turn"])
            continue
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            t = e.get("turn")
            u = _usage(p.get("usage"))
            if t is None or u is None:
                continue
            if t not in turn_rows or turn_rows[t]["status"] != "reported":
                turn_rows[t] = _turn_row(rec["seq"], e["agent_id"], t, p.get("model"), p.get("effort"), u)
        elif e["type"] == "turn.ended" and e.get("turn") is not None:
            u = _usage(p.get("usage"))
            if u is not None:
                turn_fallback[e["turn"]] = (rec["seq"], e["agent_id"], u)
    for t, (seq, agent, u) in turn_fallback.items():
        row = turn_rows.setdefault(t, _turn_row(seq, agent, t, None, None, u))
        if row.get("status") != "reported":
            row.update({"status": u["status"], "input": u["input"], "output": u["output"],
                        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                        "total_tokens": u["totalTokens"], "cost": u["cost"],
                        "context": _context_of(agent, u)})
    return [turn_rows[t] for t in sorted(turn_rows)], compaction_turns, max_turn


def _context_of(agent, u):
    # claude/pi/cue 的 input 与 cache 分列（Anthropic 语义），上下文要加回缓存；
    # codex 的 input_tokens 本身含 cached（OpenAI 语义），直接用。
    if agent in {"claude", "pi", "cue"}:
        return (u["input"] or 0) + (u["cacheRead"] or 0) + (u["cacheWrite"] or 0)
    return u["input"] or 0


def _turn_row(seq, agent, turn, model, effort, u):
    return {
        "turn": turn, "seq": seq, "agent": agent, "model": model, "effort": effort,
        "status": u["status"], "input": u["input"], "output": u["output"],
        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
        "total_tokens": u["totalTokens"], "cost": u["cost"],
        "context": _context_of(agent, u),
    }


def summarize_usage(recs):
    rows, _, _ = _usage_turns(recs)
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total_tokens": 0}
    missing = 0
    for r in rows:
        if r.get("status") == "reported":
            total["input"] += r["input"] or 0
            total["output"] += r["output"] or 0
            total["cache_read"] += r["cache_read"] or 0
            total["cache_write"] += r["cache_write"] or 0
            total["total_tokens"] += r["total_tokens"] or 0
        else:
            missing += 1
    return {"turns": rows, "total": total, "missing_turns": missing}


def audit_usage(recs):
    """usage 可信度体检：纯派生视图，随时可重算。四条规则各自只在单一方言的
    字段语义内自洽（不做 input+output=total 之类的跨字段校验，各家对 total
    是否含 cache 口径不一），宁漏勿误报。"""
    rows, compaction_turns, max_turn = _usage_turns(recs)
    by_turn = {r["turn"]: r for r in rows}
    findings = []
    for t in range(1, max_turn + 1):
        r = by_turn.get(t)
        if r is None or r.get("status") != "reported":
            detail = "该轮无 usage 记录" if r is None else f"usage status={r.get('status')}"
            findings.append({"rule": "missing", "turn": t, "detail": detail})
    reported = [r for r in rows if r.get("status") == "reported"]
    for i, r in enumerate(reported):
        # 占位值只判显式 0：claude 方言的 total_tokens 恒为 None，不能当占位。
        if r["total_tokens"] == 0:
            findings.append({"rule": "placeholder", "turn": r["turn"],
                             "detail": "reported 但 total_tokens=0，疑占位值"})
            continue
        prev = reported[i - 1] if i else None
        if prev and prev["turn"] == r["turn"] - 1:
            keys = ("input", "output", "cache_read", "cache_write", "total_tokens")
            if all((prev[k] or 0) == (r[k] or 0) for k in keys):
                findings.append({"rule": "duplicate", "turn": r["turn"],
                                 "detail": f"与第 {prev['turn']} 轮 usage 完全相同，疑流式重复写入"})
        if prev and (prev["context"] or 0) > 1000 and (r["context"] or 0) < prev["context"] / 2 \
                and r["turn"] not in compaction_turns:
            findings.append({"rule": "cliff", "turn": r["turn"],
                             "detail": f"context {prev['context']}→{r['context']} 且该轮无 compaction 标记"})
    return {"findings": findings, "reported_turns": len(reported), "expected_turns": max_turn}


def list_tools(recs, status=None, name=None):
    latest = {}
    for rec in recs:
        e = rec["event"]
        if e["type"] != "tool.upserted":
            continue
        p = e["payload"]
        cid = p.get("tool_call_id")
        row = {
            "id": cid, "seq": rec["seq"], "turn": e.get("turn"), "name": p.get("name"),
            "status": p.get("status"), "duration_ms": p.get("duration_ms"),
            "text": (p.get("text") or "")[:120] if isinstance(p.get("text"), str) else None,
            "result": p.get("result"), "started_at": e["ts"],
        }
        if latest.get(cid, {}).get("status") == "pending" or cid not in latest:
            latest[cid] = row
        else:
            latest[cid].update(row)
    rows = [latest[c] for c in sorted(latest, key=lambda c: latest[c]["started_at"])]

    def _match(row):
        if status and row["status"] != status:
            return False
        if name and name.lower() not in (row["name"] or "").lower():
            return False
        return True

    return [r for r in rows if _match(r)]


def summarize_tools(recs):
    """会话级工具调用统计：按工具名分组计数，附保序调用序列供表格钻取。

    使用率的分母取 system.upserted 的 tools_catalog 去重名字数（与投影层
    tools_index 同口径）；会话没有目录时 mounted/usage_rate 为 None，不硬算。
    """
    catalog = {}
    for rec in recs:
        e = rec["event"]
        if e["type"] != "system.upserted":
            continue
        for tool in e["payload"].get("tools_catalog") or []:
            if isinstance(tool, dict) and tool.get("name"):
                catalog[str(tool["name"])] = tool
    tools = {}
    order = []
    for row in list_tools(recs):
        g = tools.setdefault(row["name"], {"name": row["name"], "total": 0,
                                           "failed": 0, "calls": []})
        if not g["calls"]:
            order.append(row["name"])
        g["total"] += 1
        g["failed"] += 1 if row["status"] == "failed" else 0
        g["calls"].append({"seq": row["seq"], "ts": row["started_at"],
                           "status": row["status"], "duration_ms": row["duration_ms"],
                           "text": row["text"]})
    ordered = [tools[n] for n in order]
    calls = sum(g["total"] for g in ordered)
    failed = sum(g["failed"] for g in ordered)
    mounted = len(catalog) or None
    usage_rate = min(100, round(len(ordered) / mounted * 100)) if mounted else None
    return {"tools": ordered,
            "summary": {"tools": len(ordered), "calls": calls, "failed": failed,
                        "mounted": mounted, "usage_rate": usage_rate}}


# 毫秒时间戳低于此值视为脏数据（历史推送端写过 ts=1 的行），不参与墙钟
# 跨度——否则 span 被拉成 50+ 年。与 ledger._REAL_TS_FLOOR 同一约定。
_REAL_TS_FLOOR = 10 ** 12


def summarize_timing(recs):
    """会话级时间拆解（DSH 统计栏同思路）：墙钟跨度内 LLM 生成 vs 工具执行。

    duration_ms=1 或缺失视为未测量：不计入总量并把 quality 降级为
    placeholder——与 usage 的 Missing 同一诚实语义，宁缺勿假。
    同 id 多次 upsert 字典 last-wins，end 行的真实耗时覆盖 start 行的 None。
    """
    first_ts = last_ts = None
    msgs = {}   # message_id -> (turn, duration_ms)
    tools = {}  # tool_call_id -> (turn, duration_ms)
    for rec in recs:
        e = rec["event"]
        ts = e["ts"]
        if ts > _REAL_TS_FLOOR:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        p = e["payload"]
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            msgs[str(p.get("message_id"))] = (e.get("turn"), p.get("duration_ms"))
        elif e["type"] == "tool.upserted":
            tools[str(p.get("tool_call_id"))] = (e.get("turn"), p.get("duration_ms"))

    per_turn = {}

    def _cell(turn):
        return per_turn.setdefault(
            turn, {"turn": turn, "llm_ms": 0, "tool_ms": 0, "steps": 0, "calls": 0})

    llm_ms = tool_ms = 0
    llm_measured = tool_measured = False
    for turn, dur in msgs.values():
        if turn is not None:
            _cell(turn)["steps"] += 1
        if isinstance(dur, (int, float)) and dur > PLACEHOLDER_MS:
            llm_ms += dur
            llm_measured = True
            if turn is not None:
                _cell(turn)["llm_ms"] += dur
    for turn, dur in tools.values():
        if turn is not None:
            _cell(turn)["calls"] += 1
        if isinstance(dur, (int, float)) and dur > PLACEHOLDER_MS:
            tool_ms += dur
            tool_measured = True
            if turn is not None:
                _cell(turn)["tool_ms"] += dur

    def _quality(measured, count):
        if not count:
            return "n/a"
        return "measured" if measured else "placeholder"

    span_ms = max(0, last_ts - first_ts) if first_ts is not None else 0
    turn_set = {t for t, _ in msgs.values() if t is not None}
    return {
        "span_ms": span_ms,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "turns": len(turn_set),
        "steps": len(msgs),
        "calls": len(tools),
        "llm_ms": llm_ms,
        "tool_ms": tool_ms,
        "other_ms": max(0, span_ms - llm_ms - tool_ms),
        "llm_quality": _quality(llm_measured, len(msgs)),
        "tool_quality": _quality(tool_measured, len(tools)),
        "per_turn": [per_turn[t] for t in sorted(per_turn)],
    }


def list_compactions(recs):
    rows = []
    for rec in recs:
        e = rec["event"]
        if e["type"] != "compaction.boundary":
            continue
        p = e["payload"]
        rows.append({"trigger": p.get("trigger"), "pre_tokens": p.get("pre_tokens"),
                     "post_tokens": p.get("post_tokens"), "summary": p.get("summary"),
                     "ts": e["ts"]})
    return rows
