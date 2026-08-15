NA = {"status": "n/a", "input": None, "output": None, "cacheRead": None, "cacheWrite": None}
MISS = {"status": "missing", "input": None, "output": None, "cacheRead": None, "cacheWrite": None}


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
    }


def project_session(session_id, agent, recs, *, tail=None, before=None):
    title = session_id
    entities = {}
    order = []
    turn_usage = {}
    for rec in recs:
        ev = rec["event"]
        seq = rec["seq"]
        p = ev["payload"]
        if ev["type"] == "session.opened":
            title = p.get("title") or title
            continue
        if ev["type"] == "turn.ended" and p.get("usage"):
            turn_usage[ev["turn"]] = _usage(p["usage"])
            continue
        if ev["type"] == "message.upserted":
            key = ("m", p["message_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": p["message_id"],
                "_seq": seq,
                "turn": ev["turn"],
                "kind": p["role"],
                "tag": p["role"].upper(),
                "text": p["text"],
                "startedAt": p["started_at"],
                "durationMs": p.get("duration_ms") or 0,
                "status": p["status"],
                "requestNo": p.get("request_no"),
                "outputText": p.get("output_text"),
                "payloadText": p["text"] if p["role"] == "user" else None,
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
                "text": p["text"],
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

    rows = [entities[k] for k in sorted(order, key=lambda k: entities[k]["_first"])]
    step = 0
    seen_turn = set()
    for row in rows:
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
        if row["turn"] not in seen_turn:
            row["start"] = True
            seen_turn.add(row["turn"])
        else:
            row["start"] = False

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
        "crumb": f"{agent} · <b>{title}</b>",
        "has_older": has_older,
        "cursor": cursor,
        "turns": len(seen_turn),
        "rows": rows,
    }
