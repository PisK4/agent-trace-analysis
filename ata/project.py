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


def _identity(event):
    """返回 Run/Turn 完整身份；旧事件只在边界处转成 observed ordinal。"""
    if "run_id" in event or "turn_number" in event or "observed_turn_ordinal" in event:
        return (event.get("run_id"), event.get("turn_number"),
                event.get("observed_turn_ordinal"))
    # 迁移期兼容旧账本：旧 turn 不是 canonical Turn，只是观测顺序。
    legacy = event.get("turn")
    return (None, None, legacy)


def _row_identity(event):
    run_id, turn_number, observed = _identity(event)
    return {"run_id": run_id, "turn_number": turn_number,
            "observed_turn_ordinal": observed,
            # 旧 UI 的只读兼容字段；任何投影 join 都不使用它。
            "turn": turn_number if turn_number is not None else observed}


def _identity_key(row):
    return (row.get("run_id"), row.get("turn_number"),
            row.get("observed_turn_ordinal"))


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
            identity = _identity(ev)
            if p.get("usage"):
                turn_usage[identity] = _usage(p["usage"])
            if p.get("status") in {"failed", "cancelled"}:
                turn_status[identity] = p["status"]
            continue
        if ev["type"] == "message.upserted":
            # hook 执行记录等空正文 user 行（droid 修复前的存量脏数据）不进投影。
            if p["role"] == "user" and not p["text"]:
                continue
            key = ("m", *_identity(ev), p["message_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            kind, tag = _message_kind(p)
            model = p.get("model")
            effort = p.get("effort")
            identity = _row_identity(ev)
            if kind == "assistant" and model and _identity_key(identity) != (None, None, None):
                turn_model[_identity_key(identity)] = {"model": model, "effort": effort}
            row.update({
                "id": p["message_id"],
                "_seq": seq,
                **identity,
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
            key = ("t", *_identity(ev), p["tool_call_id"])
            row = entities.get(key) or {"_first": seq, "_seq": seq}
            row.update({
                "id": p["tool_call_id"],
                "_seq": seq,
                **_row_identity(ev),
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
            key = ("c", *_identity(ev), ev["id"])
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
                **_row_identity(ev),
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
                "run_id": ev.get("run_id"),
                "turn_number": None,
                "observed_turn_ordinal": None,
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
    # Round 2 收窄: 代理主发 turn 后, 投影不再 remap 孤儿 context / 孤儿
    # assistant 行的 turn 字段。context / assistant 的 turn 由 ingest 端
    # (代理 / droid / codex / pi 适配器) 决定, 投影层透传原值。
    # 老逻辑(last_user_turn / remap)已被根因 #4 验证为「压回 turn=1」污染源
    # (handoff §1 根因 #4), 代理主发后无孤儿 turn, 删之。

    seen_turn = set()
    for row in rows:
        identity = _identity_key(row)
        if row["kind"] == "assistant":
            meta = turn_model.get(identity) or {}
            if not row.get("model") and meta.get("model"):
                row["model"] = meta["model"]
                row["effort"] = meta.get("effort")
            ended = turn_status.get(identity)
            if ended and row.get("status") == "completed":
                row["status"] = ended
        if row["kind"] in {"context", "system", "compacted"} or identity == (None, None, None):
            row["start"] = False
            continue
        if identity not in seen_turn:
            row["start"] = True
            seen_turn.add(identity)
        else:
            row["start"] = False

    step = 0
    for row in rows:
        # step 是「本轮第几次请求」，轮次边界重置；system 行（turn 为 null）不重置。
        if row["start"] and _identity_key(row) != (None, None, None):
            step = 0
        if row["kind"] == "assistant":
            step += 1
            row["step"] = step
            row["group"] = f"Step {step}"
            if (not row.get("usage") or row["usage"]["status"] != "reported") and _identity_key(row) in turn_usage:
                row["usage"] = turn_usage[_identity_key(row)] or dict(MISS)
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
        "turns": len(seen_turn),
        "scores": scores,
        "tools_index": tools_index,
        "rows": rows,
    }


def tail_preview(text, n=200):
    if not isinstance(text, str) or len(text) <= n:
        return text
    return "…" + text[-n:]


def _usage_turns(recs):
    """按完整 Run/Turn identity 聚合 usage，runless 事件按 observed ordinal 隔离。"""
    turn_rows = {}
    turn_fallback = {}
    compaction_turns = set()
    for rec in recs:
        e = rec["event"]
        identity = _identity(e)
        p = e["payload"]
        if e["type"] == "compaction.boundary":
            if identity != (None, None, None):
                compaction_turns.add(identity)
            continue
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            u = _usage(p.get("usage"))
            if identity == (None, None, None) or u is None:
                continue
            if identity not in turn_rows or turn_rows[identity]["status"] != "reported":
                turn_rows[identity] = _turn_row(rec["seq"], e["agent_id"], identity,
                                                p.get("model"), p.get("effort"), u)
        elif e["type"] == "turn.ended" and identity != (None, None, None):
            u = _usage(p.get("usage"))
            if u is not None:
                turn_fallback[identity] = (rec["seq"], e["agent_id"], u)
    for identity, (seq, agent, u) in turn_fallback.items():
        row = turn_rows.setdefault(identity, _turn_row(seq, agent, identity, None, None, u))
        if row.get("status") != "reported":
            row.update({"status": u["status"], "input": u["input"], "output": u["output"],
                        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
                        "total_tokens": u["totalTokens"], "cost": u["cost"],
                        "context": _context_of(agent, u)})
    return [turn_rows[k] for k in sorted(turn_rows, key=lambda k: (k[0] is None, k))], compaction_turns


def _context_of(agent, u):
    # claude/pi/cue 的 input 与 cache 分列（Anthropic 语义），上下文要加回缓存；
    # codex 的 input_tokens 本身含 cached（OpenAI 语义），直接用。
    if agent in {"claude", "pi", "cue"}:
        return (u["input"] or 0) + (u["cacheRead"] or 0) + (u["cacheWrite"] or 0)
    return u["input"] or 0


def _turn_row(seq, agent, identity, model, effort, u):
    run_id, turn_number, observed = identity
    return {
        "run_id": run_id, "turn_number": turn_number,
        "observed_turn_ordinal": observed,
        # 旧读取方兼容别名；聚合与 join 不读取该字段。
        "turn": turn_number if turn_number is not None else observed,
        "seq": seq, "agent": agent, "model": model, "effort": effort,
        "status": u["status"], "input": u["input"], "output": u["output"],
        "cache_read": u["cacheRead"], "cache_write": u["cacheWrite"],
        "total_tokens": u["totalTokens"], "cost": u["cost"],
        "context": _context_of(agent, u),
    }


def summarize_usage(recs):
    rows, _ = _usage_turns(recs)
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
    """按每个 Run 的 Turn identity 检查缺失、占位、重复与异常 cliff。"""
    rows, compaction_turns = _usage_turns(recs)
    by_identity = {_identity_key(r): r for r in rows}
    expected = set()
    for rec in recs:
        identity = _identity(rec["event"])
        if identity[1] is not None:
            expected.add(identity)
        elif identity[2] is not None:
            expected.add(identity)
    # 仅对已观测到的每个 namespace 检查连续编号；不造 run_id=0。
    for run_id, turn_number, observed in list(expected):
        if turn_number is not None:
            expected.update((run_id, n, None) for n in range(1, turn_number + 1))
    findings = []
    for identity in sorted(expected, key=lambda x: (x[0] is None, x[0] or 0, x[1] is None, x[1] or x[2] or 0)):
        row = by_identity.get(identity)
        if row is None or row.get("status") != "reported":
            detail = "该轮无 usage 记录" if row is None else f"usage status={row.get('status')}"
            findings.append({"rule": "missing", **_identity_dict(identity), "detail": detail})
    reported = [r for r in rows if r.get("status") == "reported"]
    for i, r in enumerate(reported):
        identity = _identity_key(r)
        if r["total_tokens"] == 0:
            findings.append({"rule": "placeholder", **_identity_dict(identity),
                             "detail": "reported 但 total_tokens=0，疑占位值"})
            continue
        prev = reported[i - 1] if i else None
        previous = _identity_key(prev) if prev else None
        previous_number = (previous[1] if previous and previous[1] is not None else
                           previous[2] if previous else None)
        current_number = identity[1] if identity[1] is not None else identity[2]
        if prev and previous[0] == identity[0] and previous_number is not None \
                and current_number == previous_number + 1:
            keys = ("input", "output", "cache_read", "cache_write", "total_tokens")
            if all((prev[k] or 0) == (r[k] or 0) for k in keys):
                findings.append({"rule": "duplicate", **_identity_dict(identity),
                                 "detail": "与上一轮 usage 完全相同，疑流式重复写入"})
        if prev and previous[0] == identity[0] and (prev["context"] or 0) > 1000 \
                and (r["context"] or 0) < prev["context"] / 2 and identity not in compaction_turns:
            findings.append({"rule": "cliff", **_identity_dict(identity),
                             "detail": f"context {prev['context']}→{r['context']} 且该轮无 compaction 标记"})
    return {"findings": findings, "reported_turns": len(reported), "expected_turns": len(expected)}


def _identity_dict(identity):
    run_id, turn_number, observed = identity
    return {"run_id": run_id, "turn_number": turn_number,
            "observed_turn_ordinal": observed,
            # 兼容现有 CLI/UI 展示，禁止作为自然键使用。
            "turn": turn_number if turn_number is not None else observed}


def list_tools(recs, status=None, name=None):
    latest = {}
    for rec in recs:
        e = rec["event"]
        if e["type"] != "tool.upserted":
            continue
        p = e["payload"]
        identity = _identity(e)
        cid = p.get("tool_call_id")
        key = (*identity, cid)
        row = {
            "id": cid, "seq": rec["seq"], **_identity_dict(identity),
            "name": p.get("name"), "status": p.get("status"),
            "duration_ms": p.get("duration_ms"),
            "text": (p.get("text") or "")[:120] if isinstance(p.get("text"), str) else None,
            "result": p.get("result"), "started_at": e["ts"],
        }
        if latest.get(key, {}).get("status") == "pending" or key not in latest:
            latest[key] = row
        else:
            latest[key].update(row)
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
    """按完整 Run/Turn identity 拆解 LLM 与工具耗时。"""
    first_ts = last_ts = None
    msgs = {}   # message_id + identity -> (identity, duration_ms)
    tools = {}  # tool_call_id + identity -> (identity, duration_ms)
    for rec in recs:
        e = rec["event"]
        ts = e["ts"]
        if ts > _REAL_TS_FLOOR:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        p = e["payload"]
        identity = _identity(e)
        if e["type"] == "message.upserted" and p.get("role") == "assistant":
            msgs[(*identity, str(p.get("message_id")))] = (identity, p.get("duration_ms"))
        elif e["type"] == "tool.upserted":
            tools[(*identity, str(p.get("tool_call_id")))] = (identity, p.get("duration_ms"))

    per_turn = {}

    def _cell(identity):
        return per_turn.setdefault(identity, {**_identity_dict(identity), "llm_ms": 0,
                                               "tool_ms": 0, "steps": 0, "calls": 0})

    llm_ms = tool_ms = 0
    llm_measured = tool_measured = False
    for identity, dur in msgs.values():
        if identity != (None, None, None):
            _cell(identity)["steps"] += 1
        if isinstance(dur, (int, float)) and dur > PLACEHOLDER_MS:
            llm_ms += dur
            llm_measured = True
            if identity != (None, None, None):
                _cell(identity)["llm_ms"] += dur
    for identity, dur in tools.values():
        if identity != (None, None, None):
            _cell(identity)["calls"] += 1
        if isinstance(dur, (int, float)) and dur > PLACEHOLDER_MS:
            tool_ms += dur
            tool_measured = True
            if identity != (None, None, None):
                _cell(identity)["tool_ms"] += dur

    def _quality(measured, count):
        if not count:
            return "n/a"
        return "measured" if measured else "placeholder"

    span_ms = max(0, last_ts - first_ts) if first_ts is not None else 0
    turn_set = {identity for identity, _ in msgs.values() if identity != (None, None, None)}
    return {
        "span_ms": span_ms, "first_ts": first_ts, "last_ts": last_ts,
        "turns": len(turn_set), "steps": len(msgs), "calls": len(tools),
        "llm_ms": llm_ms, "tool_ms": tool_ms,
        "other_ms": max(0, span_ms - llm_ms - tool_ms),
        "llm_quality": _quality(llm_measured, len(msgs)),
        "tool_quality": _quality(tool_measured, len(tools)),
        "per_turn": [per_turn[t] for t in sorted(per_turn, key=lambda x: (x[0] is None, x))],
    }


def list_compactions(recs):
    rows = []
    for rec in recs:
        e = rec["event"]
        if e["type"] != "compaction.boundary":
            continue
        p = e["payload"]
        rows.append({**_identity_dict(_identity(e)), "trigger": p.get("trigger"),
                     "pre_tokens": p.get("pre_tokens"), "post_tokens": p.get("post_tokens"),
                     "summary": p.get("summary"), "ts": e["ts"]})
    return rows

