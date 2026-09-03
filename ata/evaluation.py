"""Evaluation 事实的校验、追加与折叠。

Evaluation 与 Runtime Session 使用同一个 Ledger writer，但事实存放在独立
的 evaluation_events 表中；Evaluation 不复制 Session score，也不拥有 Run。
"""

from __future__ import annotations

import time
import uuid


EVALUATION_TYPES = {
    "evaluation.created",
    "evaluation.renamed",
    "evaluation.deleted",
    "evaluation.session.added",
    "evaluation.session.removed",
}


class EvaluationValidationError(ValueError):
    """Evaluation fact 或操作违反契约。"""


def _require_text(value, name):
    if not isinstance(value, str) or not value:
        raise EvaluationValidationError(f"{name} required")


def validate_fact(raw: dict) -> dict:
    """校验并复制 Evaluation fact；它不走 Runtime event schema。"""
    if not isinstance(raw, dict):
        raise EvaluationValidationError("fact must be object")
    for key in ("v", "id", "evaluation_id", "ts", "type", "payload"):
        if key not in raw:
            raise EvaluationValidationError(f"missing {key}")
    if raw["v"] != 1:
        raise EvaluationValidationError("v must be 1")
    _require_text(raw["id"], "id")
    _require_text(raw["evaluation_id"], "evaluation_id")
    if not isinstance(raw["ts"], (int, float)) or isinstance(raw["ts"], bool):
        raise EvaluationValidationError("bad ts")
    if raw["type"] not in EVALUATION_TYPES:
        raise EvaluationValidationError("bad evaluation type")
    if not isinstance(raw["payload"], dict):
        raise EvaluationValidationError("payload must be object")

    typ, payload = raw["type"], raw["payload"]
    if typ in {"evaluation.created", "evaluation.renamed"}:
        _require_text(payload.get("title"), "title")
    elif typ == "evaluation.session.added":
        _require_text(payload.get("session_id"), "session_id")
        if not isinstance(payload.get("task_label"), str):
            raise EvaluationValidationError("task_label must be string")
    elif typ == "evaluation.session.removed":
        _require_text(payload.get("session_id"), "session_id")
    elif payload:
        raise EvaluationValidationError("deleted payload must be empty")
    return {
        "v": 1,
        "id": str(raw["id"]),
        "evaluation_id": str(raw["evaluation_id"]),
        "ts": int(raw["ts"]),
        "type": raw["type"],
        "payload": dict(payload),
    }


def evaluation_envelope(evaluation_id, type_, payload, *, ts=None, eid=None) -> dict:
    """构造 Evaluation fact；写入前仍由 validate_fact 做边界校验。"""
    return {
        "v": 1,
        "id": eid or uuid.uuid4().hex,
        "evaluation_id": str(evaluation_id),
        "ts": int(ts if ts is not None else time.time() * 1000),
        "type": type_,
        "payload": payload,
    }


def fold_evaluation_events(evaluation_id: str, records: list[dict]) -> dict | None:
    """按 Evaluation-local seq 折叠 title、删除态和 active membership。"""
    state = {
        "evaluation_id": evaluation_id,
        "title": None,
        "deleted": False,
        "members": {},
    }
    seen = False
    for record in records:
        event = record.get("event", record)
        payload = event.get("payload") or {}
        typ = event.get("type")
        seen = True
        if typ == "evaluation.created":
            # 删除是 identity 的终态；即使旧账本已有非法 created，也不能复活。
            if not state["deleted"]:
                state["title"] = payload.get("title")
        elif typ == "evaluation.renamed":
            state["title"] = payload.get("title")
        elif typ == "evaluation.deleted":
            state["deleted"] = True
            state["members"].clear()
        elif typ == "evaluation.session.added" and not state["deleted"]:
            sid = payload.get("session_id")
            state["members"][sid] = {
                "session_id": sid,
                "task_label": payload.get("task_label", ""),
                "ts": int(event.get("ts") or 0),
                "seq": int(record.get("seq", 0)),
            }
        elif typ == "evaluation.session.removed" and not state["deleted"]:
            state["members"].pop(payload.get("session_id"), None)
    if not seen:
        return None
    state["members"] = sorted(
        state["members"].values(), key=lambda item: (item["seq"], item["session_id"])
    )
    return state


class EvaluationStore:
    """在 Ledger 内管理 Evaluation facts 与 membership。"""

    def __init__(self, ledger):
        self.ledger = ledger

    def append(self, raw: dict) -> int:
        """追加 fact；同一 Evaluation 下重复 fact id 幂等。"""
        fact = validate_fact(raw)
        with self.ledger.transaction() as tx:
            for record in self.ledger.read_evaluation_events(fact["evaluation_id"]):
                if record["event"]["id"] == fact["id"]:
                    return int(record["seq"])
            self._validate_transition(fact)
            return tx.append_evaluation(fact)

    def _validate_transition(self, fact: dict):
        """在 Ledger 事务内调用；阻止未知或已删除 identity 的状态变更。"""
        evaluation_id = fact["evaluation_id"]
        state = self.ledger.fold_evaluation(evaluation_id)
        if fact["type"] == "evaluation.created":
            if state is not None:
                raise EvaluationValidationError("evaluation already exists")
            return
        if state is None:
            raise EvaluationValidationError("evaluation not found")
        if state["deleted"]:
            raise EvaluationValidationError("evaluation deleted")

    def read(self, evaluation_id: str) -> list[dict]:
        return self.ledger.read_evaluation_events(evaluation_id)

    def fold(self, evaluation_id: str) -> dict | None:
        return self.ledger.fold_evaluation(evaluation_id)

    def evaluations(self) -> list[dict]:
        return [self.fold(eid) for eid in self.ledger.evaluation_ids()]

    list = evaluations

    def create(self, title: str, *, evaluation_id: str | None = None, ts=None) -> str:
        _require_text(title, "title")
        eid = evaluation_id or f"e-{uuid.uuid4().hex}"
        with self.ledger.transaction() as tx:
            if self.ledger.fold_evaluation(eid) is not None:
                raise EvaluationValidationError("evaluation already exists")
            fact = validate_fact(evaluation_envelope(
                eid, "evaluation.created", {"title": title}, ts=ts,
            ))
            tx.append_evaluation(fact)
        return eid

    def rename(self, evaluation_id: str, title: str, *, ts=None) -> int:
        self._require_active(evaluation_id)
        return self.append(evaluation_envelope(
            evaluation_id, "evaluation.renamed", {"title": title}, ts=ts
        ))

    def delete(self, evaluation_id: str, *, ts=None) -> int:
        self._require_active(evaluation_id)
        return self.append(evaluation_envelope(
            evaluation_id, "evaluation.deleted", {}, ts=ts
        ))

    def add_session(self, evaluation_id: str, session_id: str, task_label: str = "", *, ts=None) -> int:
        _require_text(session_id, "session_id")
        if not isinstance(task_label, str):
            raise EvaluationValidationError("task_label must be string")
        with self.ledger.transaction() as tx:
            current = self.ledger.fold_evaluation(evaluation_id)
            if current is None:
                raise EvaluationValidationError("evaluation not found")
            if current["deleted"]:
                raise EvaluationValidationError("evaluation deleted")
            if self.ledger.session(session_id) is None:
                raise EvaluationValidationError("session not found")
            for other_id in self.ledger.evaluation_ids():
                if other_id == evaluation_id:
                    continue
                other = self.ledger.fold_evaluation(other_id)
                if other and not other["deleted"] and any(
                    member["session_id"] == session_id for member in other["members"]
                ):
                    raise EvaluationValidationError("session already in another evaluation")
            fact = validate_fact(evaluation_envelope(
                evaluation_id, "evaluation.session.added",
                {"session_id": session_id, "task_label": task_label}, ts=ts,
            ))
            return tx.append_evaluation(fact)

    def remove_session(self, evaluation_id: str, session_id: str, *, ts=None) -> int:
        _require_text(session_id, "session_id")
        with self.ledger.transaction() as tx:
            current = self.ledger.fold_evaluation(evaluation_id)
            if current is None:
                raise EvaluationValidationError("evaluation not found")
            if current["deleted"]:
                raise EvaluationValidationError("evaluation deleted")
            if not any(member["session_id"] == session_id for member in current["members"]):
                raise EvaluationValidationError("session membership not found")
            fact = validate_fact(evaluation_envelope(
                evaluation_id, "evaluation.session.removed", {"session_id": session_id}, ts=ts,
            ))
            return tx.append_evaluation(fact)

    def _require_active(self, evaluation_id: str):
        state = self.fold(evaluation_id)
        if state is None:
            raise EvaluationValidationError("evaluation not found")
        if state["deleted"]:
            raise EvaluationValidationError("evaluation deleted")
