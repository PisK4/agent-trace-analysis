import json

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


# dsh 把非用户输入的注入消息标成 CONTEXT（system-reminder / skill 清单 /
# TodoWrite 提醒）。ATA 语料里这些仍走 user 角色，投影时按正文前缀改标。
_CONTEXT_PREFIXES = (
    "<system-reminder>",
    "<system-notification>",
    "Skill \"",
    "Skill '",
)


def is_context_text(text):
    raw = (text or "").lstrip()
    return any(raw.startswith(prefix) for prefix in _CONTEXT_PREFIXES)


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
    title = session_id
    entities = {}
    order = []
    turn_usage = {}
    turn_status = {}
    turn_model = {}
    for rec in recs:
        ev = rec["event"]
        seq = rec["seq"]
        p = ev["payload"]
        if ev["type"] == "session.opened":
            title = p.get("title") or title
            continue
        if ev["type"] == "turn.ended":
            if p.get("usage"):
                turn_usage[ev["turn"]] = _usage(p["usage"])
            if p.get("status") in {"failed", "cancelled"}:
                turn_status[ev["turn"]] = p["status"]
            continue
        if ev["type"] == "message.upserted":
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
            catalog = p.get("tools_catalog") or []
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
                "toolsCatalog": catalog,
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
    return {
        "id": session_id,
        "agent": agent,
        "title": title,
        # 标题可能来自用户消息原文，crumb 走 innerHTML，必须转义。
        "crumb": f"{agent} · <b>{_esc(title)}</b>",
        "has_older": has_older,
        "cursor": cursor,
        "turns": len({t for t in seen_turn if t is not None}),
        "tools_index": tools_index,
        "rows": rows,
    }


def tail_preview(text, n=200):
    if not isinstance(text, str) or len(text) <= n:
        return text
    return "…" + text[-n:]


def summarize_usage(recs):
    turn_rows = {}
    turn_fallback = {}
    for rec in recs:
        e = rec["event"]
        p = e["payload"]
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            t = e.get("turn")
            u = _usage(p.get("usage"))
            if t is None or u is None:
                continue
            if t not in turn_rows or turn_rows[t]["status"] != "reported":
                turn_rows[t] = {
                    "turn": t, "model": p.get("model"), "effort": p.get("effort"),
                    "status": u["status"], "input": u["input"], "output": u["output"],
                    "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                    "total_tokens": u["totalTokens"], "cost": u["cost"],
                }
        elif e["type"] == "turn.ended" and e.get("turn") is not None:
            u = _usage(p.get("usage"))
            if u is not None:
                turn_fallback[e["turn"]] = u
    for t, u in turn_fallback.items():
        row = turn_rows.setdefault(t, {"turn": t, "model": None, "effort": None})
        if row.get("status") != "reported":
            row.update({"status": u["status"], "input": u["input"], "output": u["output"],
                        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                        "total_tokens": u["totalTokens"], "cost": u["cost"]})
    rows = [turn_rows[t] for t in sorted(turn_rows)]
    total = {"input": 0, "output": 0, "total_tokens": 0}
    missing = 0
    for r in rows:
        if r.get("status") == "reported":
            total["input"] += r["input"] or 0
            total["output"] += r["output"] or 0
            total["total_tokens"] += r["total_tokens"] or 0
        else:
            missing += 1
    return {"turns": rows, "total": total, "missing_turns": missing}


def list_tools(recs, status=None, name=None):
    latest = {}
    for rec in recs:
        e = rec["event"]
        if e["type"] != "tool.upserted":
            continue
        p = e["payload"]
        cid = p.get("tool_call_id")
        row = {
            "id": cid, "turn": e.get("turn"), "name": p.get("name"),
            "status": p.get("status"), "duration_ms": p.get("duration_ms"),
            "result": p.get("result"), "started_at": e["ts"],
        }
        if latest.get(cid, {}).get("status") == "pending" or cid not in latest:
            latest[cid] = row
        else:
            latest[cid].update(row)
    rows = [latest[c] for c in sorted(latest, key=lambda c: latest[c]["started_at"])]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if name:
        rows = [r for r in rows if r["name"] == name]
    return rows


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
