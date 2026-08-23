ALLOWED_TYPES = {
    "session.opened",
    "turn.started",
    "message.upserted",
    "tool.upserted",
    "turn.ended",
    "session.closed",
    "system.upserted",
    "compaction.boundary",
    "session.scored",
    "session.assigned",
}
ALLOWED_AGENTS = {"pi", "cue", "droid", "claude", "codex"}
USAGE_KEYS = ("status", "input", "output", "cache_read", "cache_write", "total_tokens", "cost")


class ValidationError(ValueError):
    pass


def parse_event(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("event must be object")
    for key in ("v", "id", "agent_id", "session_id", "ts", "type", "payload"):
        if key not in raw:
            raise ValidationError(f"missing {key}")
    if raw["v"] != 1:
        raise ValidationError("v must be 1")
    if raw["agent_id"] not in ALLOWED_AGENTS:
        raise ValidationError("bad agent_id")
    if not raw["session_id"] or not raw["id"]:
        raise ValidationError("empty id")
    if not isinstance(raw["ts"], (int, float)):
        raise ValidationError("bad ts")
    if raw["type"] not in ALLOWED_TYPES:
        raise ValidationError("bad type")
    if not isinstance(raw["payload"], dict):
        raise ValidationError("payload must be object")
    turn = raw.get("turn", None)
    if raw["type"].startswith("session.") or raw["type"] == "system.upserted":
        if turn is not None:
            raise ValidationError("session/system turn must be null")
    elif not isinstance(turn, int) or turn < 1:
        raise ValidationError("turn must be positive int")
    _check_payload(raw["type"], raw["payload"])
    return {
        "v": 1,
        "id": str(raw["id"]),
        "agent_id": raw["agent_id"],
        "session_id": str(raw["session_id"]),
        "ts": int(raw["ts"]),
        "type": raw["type"],
        "turn": turn,
        "payload": raw["payload"],
    }


def _check_payload(typ, p):
    if typ == "session.opened" and not p.get("title"):
        raise ValidationError("title required")
    if typ == "system.upserted" and not p.get("prompt_text"):
        raise ValidationError("prompt_text required")
    if typ == "message.upserted":
        if p.get("role") not in {"user", "assistant"}:
            raise ValidationError("bad role")
        if not p.get("message_id"):
            raise ValidationError("message_id required")
        if p["role"] == "user" and p.get("usage") is not None:
            raise ValidationError("user usage must be null")
        if p["role"] == "assistant" and p.get("usage") is not None:
            _check_usage(p["usage"])
    if typ == "tool.upserted" and not p.get("tool_call_id"):
        raise ValidationError("tool_call_id required")
    if typ == "compaction.boundary" and not p.get("summary"):
        raise ValidationError("summary required")
    if typ == "turn.ended" and p.get("usage") is not None:
        _check_usage(p["usage"])
    if typ == "session.scored":
        if p.get("value") not in {"good", "bad", "partial"}:
            raise ValidationError("bad score value")
        if "note" in p and not isinstance(p["note"], str):
            raise ValidationError("score note must be string")
    if typ == "session.assigned":
        for key in ("run_id", "task_id"):
            if not isinstance(p.get(key), str) or not p[key]:
                raise ValidationError(f"{key} required")


def _check_usage(u):
    if not isinstance(u, dict) or u.get("status") not in {"reported", "estimated", "missing"}:
        raise ValidationError("bad usage")
    for k in USAGE_KEYS:
        if k not in u:
            raise ValidationError(f"usage missing {k}")
