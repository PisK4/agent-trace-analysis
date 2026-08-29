import time
import uuid

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
    "session.score.cleared",
    "session.renamed",
    "run.started",
    "run.ended",
    "run.lifecycle.conflict",
}
ALLOWED_AGENTS = {"pi", "cue", "droid", "claude", "codex"}
USAGE_KEYS = ("status", "input", "output", "cache_read", "cache_write", "total_tokens", "cost")
_SESSION_TYPES = {
    "session.opened",
    "session.renamed",
    "session.closed",
    "session.scored",
    "session.score.cleared",
}
_TURN_TYPES = {"turn.started", "message.upserted", "tool.upserted", "turn.ended"}


class ValidationError(ValueError):
    pass


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        raise ValidationError(f"{name} must be positive int")


def _nullable_positive_int(value, name):
    if value is not None:
        _positive_int(value, name)


def _check_identity(raw):
    run_id = raw.get("run_id")
    turn_number = raw.get("turn_number")
    observed = raw.get("observed_turn_ordinal")
    _nullable_positive_int(run_id, "run_id")
    _nullable_positive_int(turn_number, "turn_number")
    _nullable_positive_int(observed, "observed_turn_ordinal")
    if turn_number is not None and run_id is None:
        raise ValidationError("turn_number requires run_id")
    if observed is not None and (run_id is not None or turn_number is not None):
        raise ValidationError("canonical and observed turn identity are exclusive")
    return run_id, turn_number, observed


def parse_event(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("event must be object")
    for key in ("v", "id", "agent_id", "session_id", "ts", "type", "payload"):
        if key not in raw:
            raise ValidationError(f"missing {key}")
    if "turn" in raw:
        raise ValidationError("turn field removed; use turn_number")
    if raw["v"] != 1:
        raise ValidationError("v must be 1")
    if raw["agent_id"] not in ALLOWED_AGENTS:
        raise ValidationError("bad agent_id")
    if not raw["session_id"] or not raw["id"]:
        raise ValidationError("empty id")
    if not isinstance(raw["ts"], (int, float)) or isinstance(raw["ts"], bool):
        raise ValidationError("bad ts")
    if raw["type"] not in ALLOWED_TYPES:
        raise ValidationError("bad type")
    if not isinstance(raw["payload"], dict):
        raise ValidationError("payload must be object")
    run_id, turn_number, observed = _check_identity(raw)
    typ = raw["type"]
    if typ in _SESSION_TYPES or typ == "run.lifecycle.conflict":
        if run_id is not None or turn_number is not None or observed is not None:
            raise ValidationError("session/conflict identity must be null")
    elif typ in {"run.started", "run.ended"}:
        if run_id is None or turn_number is not None or observed is not None:
            raise ValidationError("run boundary requires run_id only")
    elif typ in {"system.upserted", "compaction.boundary"}:
        if turn_number is not None or observed is not None:
            raise ValidationError("system/compaction turn identity must be null")
    elif typ in _TURN_TYPES:
        canonical = run_id is not None and turn_number is not None and observed is None
        observed_only = run_id is None and turn_number is None and observed is not None
        if not (canonical or observed_only):
            raise ValidationError("turn event requires canonical or observed identity")
    _check_payload(typ, raw["payload"])
    return {
        "v": 1,
        "id": str(raw["id"]),
        "agent_id": raw["agent_id"],
        "session_id": str(raw["session_id"]),
        "ts": int(raw["ts"]),
        "type": typ,
        "run_id": run_id,
        "turn_number": turn_number,
        "observed_turn_ordinal": observed,
        "payload": raw["payload"],
    }


def _check_payload(typ, p):
    if typ == "session.opened" and not p.get("title"):
        raise ValidationError("title required")
    if typ == "system.upserted" and not p.get("prompt_text"):
        raise ValidationError("prompt_text required")
    if typ in {"run.started", "run.ended"}:
        if "external_lifecycle_id" not in p:
            raise ValidationError("external_lifecycle_id required")
        if p["external_lifecycle_id"] is not None and not isinstance(p["external_lifecycle_id"], str):
            raise ValidationError("external_lifecycle_id must be string or null")
        if not isinstance(p.get("boundary_source"), str) or not p["boundary_source"]:
            raise ValidationError("boundary_source required")
    if typ == "run.lifecycle.conflict":
        if "external_lifecycle_id" not in p:
            raise ValidationError("external_lifecycle_id required")
        if p["external_lifecycle_id"] is not None and not isinstance(p["external_lifecycle_id"], str):
            raise ValidationError("external_lifecycle_id must be string or null")
        for key in ("hook_name", "reason", "semantic_fingerprint", "boundary_source"):
            if not isinstance(p.get(key), str) or not p[key]:
                raise ValidationError(f"{key} required")
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
    if typ == "session.renamed" and not (p.get("title") or "").strip():
        raise ValidationError("title required")


def _check_usage(u):
    if not isinstance(u, dict) or u.get("status") not in {"reported", "estimated", "missing"}:
        raise ValidationError("bad usage")
    for k in USAGE_KEYS:
        if k not in u:
            raise ValidationError(f"usage missing {k}")


def envelope(
    agent_id,
    session_id,
    type_,
    payload,
    turn=None,
    *,
    run_id=None,
    turn_number=None,
    observed_turn_ordinal=None,
    ts=None,
    eid=None,
):
    """构造保留完整 Runtime identity 的 v1 事件信封。

    ``turn`` 仅为旧 fixture/adapter 的输入兼容别名，输出永远使用 observed
    ordinal；新代码必须使用 run_id/turn_number 或 observed_turn_ordinal。
    """
    if turn is not None:
        if turn_number is not None or observed_turn_ordinal is not None:
            raise ValidationError("legacy turn conflicts with runtime identity")
        observed_turn_ordinal = turn
    return {
        "v": 1,
        "id": eid if eid is not None else uuid.uuid4().hex,
        "agent_id": agent_id,
        "session_id": str(session_id),
        "ts": int(ts if ts is not None else time.time() * 1000),
        "type": type_,
        "run_id": run_id,
        "turn_number": turn_number,
        "observed_turn_ordinal": observed_turn_ordinal,
        "payload": payload,
    }
