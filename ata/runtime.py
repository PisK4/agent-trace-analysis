from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from ata.ledger import Ledger
from ata.schema import envelope, parse_event


@dataclass(frozen=True)
class RuntimeScope:
    """一个可写入 Runtime event 的 canonical 或 observed identity。"""

    run_id: int | None = None
    turn_number: int | None = None
    observed_turn_ordinal: int | None = None


class RuntimeCoordinator:
    """在 Ledger 单 writer 边界内关联 Run，并为 Turn 分配本地身份。"""

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    @staticmethod
    def _fingerprint(phase: str, session_id: str, external_lifecycle_id: str | None,
                     payload: dict[str, Any] | None) -> str:
        """去掉 delivery timestamp/id 后生成稳定的生命周期语义指纹。"""
        material = {"phase": phase, "session_id": session_id,
                    "external_lifecycle_id": external_lifecycle_id,
                    "payload": payload or {}}
        return hashlib.sha256(json.dumps(material, sort_keys=True,
                                         ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def lifecycle(self, *, phase: str, session_id: str,
                  external_lifecycle_id: str | None = None,
                  boundary_source: str, agent_id: str = "pi",
                  ts: int | None = None,
                  payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """接收 agent_start/agent_end 证据，返回 created/matched/duplicate/conflict。"""
        if phase not in {"start", "end"}:
            raise ValueError("phase must be start or end")
        with self.ledger._lock:
            if phase == "start":
                return self._start_locked(session_id, external_lifecycle_id,
                                          boundary_source, agent_id, ts, payload)
            return self._end_locked(session_id, external_lifecycle_id,
                                    boundary_source, agent_id, ts, payload)

    def start(self, session_id: str, *, external_lifecycle_id: str | None = None,
              boundary_source: str = "runtime", agent_id: str = "pi", ts: int | None = None,
              payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.lifecycle(phase="start", session_id=session_id,
                              external_lifecycle_id=external_lifecycle_id,
                              boundary_source=boundary_source, agent_id=agent_id,
                              ts=ts, payload=payload)

    def end(self, session_id: str, *, external_lifecycle_id: str | None = None,
            boundary_source: str = "runtime", agent_id: str = "pi", ts: int | None = None,
            payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.lifecycle(phase="end", session_id=session_id,
                              external_lifecycle_id=external_lifecycle_id,
                              boundary_source=boundary_source, agent_id=agent_id,
                              ts=ts, payload=payload)

    def _boundary_event(self, session_id: str, typ: str, run_id: int | None,
                       external: str | None, source: str, agent_id: str,
                       ts: int | None, payload: dict[str, Any] | None = None) -> dict:
        body = dict(payload or {})
        body.update({"external_lifecycle_id": external, "boundary_source": source})
        return parse_event(envelope(agent_id, session_id, typ, body, run_id=run_id, ts=ts))

    def _start_locked(self, sid: str, external: str | None, source: str, agent_id: str,
                      ts: int | None, payload: dict[str, Any] | None) -> dict[str, Any]:
        if external is None:
            reason = "lifecycle id required"
            return self._conflict(
                sid, external, source, reason,
                self._fingerprint("start", sid, external, payload), ts, agent_id,
            )
        rows = self.ledger.runs(sid)
        if external is not None:
            same = [r for r in rows if r["external_lifecycle_id"] == external]
            if same:
                run = same[0]
                prior = self._start_fingerprint(sid, run["run_id"])
                current = self._fingerprint("start", sid, external, payload)
                if prior == current:
                    return {"status": "duplicate", "scope": RuntimeScope(run["run_id"])}
                return self._conflict(sid, external, source, "lifecycle id reused with different semantic payload", current, ts, agent_id)
        run_id = max((int(r["run_id"]) for r in rows), default=0) + 1
        event = self._boundary_event(sid, "run.started", run_id, external, source, agent_id, ts, payload)
        self.ledger._append_locked(event)
        self.ledger._conn.commit()
        return {"status": "created", "scope": RuntimeScope(run_id=run_id)}

    def _end_locked(self, sid: str, external: str | None, source: str, agent_id: str,
                    ts: int | None, payload: dict[str, Any] | None) -> dict[str, Any]:
        if external is None:
            reason = "lifecycle id required"
            return self._conflict(
                sid, external, source, reason,
                self._fingerprint("end", sid, external, payload), ts, agent_id,
            )
        rows = self.ledger.runs(sid)
        matches = [r for r in rows if r["external_lifecycle_id"] == external]
        if len(matches) != 1:
            reason = "end has no matching start" if not matches else "end has ambiguous lifecycle id"
            fp = self._fingerprint("end", sid, external, payload)
            return self._conflict(sid, external, source, reason, fp, ts, agent_id)
        run = matches[0]
        if run["status"] == "ended":
            prior = self._end_fingerprint(sid, int(run["run_id"]))
            current = self._fingerprint("end", sid, external, payload)
            if prior == current:
                return {"status": "duplicate", "scope": RuntimeScope(run["run_id"])}
            return self._conflict(sid, external, source, "lifecycle end reused with different semantic payload", current, ts, agent_id)
        event = self._boundary_event(sid, "run.ended", int(run["run_id"]), external, source, agent_id, ts, payload)
        self.ledger._append_locked(event)
        self.ledger._conn.commit()
        return {"status": "matched", "scope": RuntimeScope(run_id=int(run["run_id"]))}

    def _conflict(self, sid: str, external: str | None, source: str,
                  reason: str, fingerprint: str, ts: int | None,
                  agent_id: str) -> dict[str, Any]:
        event = envelope(agent_id, sid, "run.lifecycle.conflict", {
            "external_lifecycle_id": external, "hook_name": source,
            "reason": reason, "semantic_fingerprint": fingerprint,
            "boundary_source": source,
        }, ts=ts, eid=f"{sid}:lifecycle-conflict:{fingerprint}")
        self.ledger._append_locked(parse_event(event))
        self.ledger._conn.commit()
        return {"status": "conflict", "scope": None, "reason": reason}

    def _end_fingerprint(self, sid: str, run_id: int) -> str | None:
        for row in self.ledger.read(sid):
            event = row["event"]
            if event.get("type") == "run.ended" and event.get("run_id") == run_id:
                payload = event.get("payload") or {}
                external = payload.get("external_lifecycle_id")
                body = {k: v for k, v in payload.items()
                        if k not in {"external_lifecycle_id", "boundary_source"}}
                return self._fingerprint("end", sid, external, body)
        return None

    def _start_fingerprint(self, sid: str, run_id: int) -> str | None:
        for row in self.ledger.read(sid):
            event = row["event"]
            if event.get("type") == "run.started" and event.get("run_id") == run_id:
                return self._fingerprint("start", sid,
                                         (event.get("payload") or {}).get("external_lifecycle_id"),
                                         {k: v for k, v in (event.get("payload") or {}).items()
                                          if k not in {"external_lifecycle_id", "boundary_source"}})
        return None

    def scope_for_event(self, session_id: str) -> RuntimeScope:
        """无 lifecycle ID 的普通事件只继承无冲突的唯一 open Run。"""
        records = self.ledger.read(session_id)
        if any(r["event"].get("type") == "run.lifecycle.conflict" for r in records):
            return RuntimeScope(observed_turn_ordinal=self._next_observed(session_id))
        open_runs = self.ledger.open_runs(session_id)
        if len(open_runs) == 1:
            return RuntimeScope(run_id=int(open_runs[0]["run_id"]))
        return RuntimeScope(observed_turn_ordinal=self._next_observed(session_id))

    def allocate_turn(self, session_id: str, run_id: int | None = None) -> RuntimeScope:
        """为 Run 分配下一个 Turn；无唯一 Run 时返回显式 observed ordinal。"""
        with self.ledger._lock:
            if run_id is None:
                scope = self.scope_for_event(session_id)
                if scope.run_id is None:
                    return scope
                run_id = scope.run_id
            run = self.ledger.run(session_id, int(run_id))
            if run is None:
                raise ValueError("unknown run")
            return RuntimeScope(run_id=int(run_id), turn_number=int(run["max_turn_number"]) + 1)

    def _next_observed(self, sid: str) -> int:
        rows = self.ledger.read(sid)
        return max((int(e["event"].get("observed_turn_ordinal") or 0) for e in rows), default=0) + 1

    def emit(self, *, agent_id: str, session_id: str, type_: str, payload: dict,
             scope: RuntimeScope | None = None, ts: int | None = None,
             eid: str | None = None) -> int:
        """用已分配 scope 发出 Runtime event，不为旧事件回填 identity。"""
        scope = scope or RuntimeScope()
        event = envelope(agent_id, session_id, type_, payload,
                         run_id=scope.run_id, turn_number=scope.turn_number,
                         observed_turn_ordinal=scope.observed_turn_ordinal,
                         ts=ts, eid=eid)
        return self.ledger.append(parse_event(event))


__all__ = ["RuntimeCoordinator", "RuntimeScope"]
