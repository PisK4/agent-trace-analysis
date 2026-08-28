"""Runtime read facade：HTTP、CLI 与未来读取端共用同一组派生口径。"""

from ata.project import (
    audit_usage,
    list_compactions,
    list_tools,
    project_session,
    summarize_timing,
    summarize_tools,
    summarize_usage,
    tail_preview,
)


def list_runs(store, session_id):
    """只读取指定 Session 的已观察 Run，不建立全局 Run 视图。"""
    return store.runs(session_id)


def run_detail(store, session_id, run_id):
    try:
        run_id = int(run_id)
    except (TypeError, ValueError):
        return None
    run = store.run(session_id, run_id)
    if run is None:
        return None
    run = dict(run)
    run["turns"] = list_turns(store, session_id, run_id=run_id)
    return run


def list_turns(store, session_id, run_id=None):
    """按完整 identity 折叠 Turn；runless 事件不会猜测归属。"""
    turns = {}
    for record in store.read(session_id):
        event = record["event"]
        rid = event.get("run_id")
        number = event.get("turn_number")
        observed = event.get("observed_turn_ordinal")
        if run_id is not None and rid != run_id:
            continue
        if rid is not None and number is not None:
            key = ("canonical", rid, number)
            identity = {"run_id": rid, "turn_number": number,
                        "observed_turn_ordinal": None}
        elif observed is not None:
            key = ("observed", observed)
            identity = {"run_id": None, "turn_number": None,
                        "observed_turn_ordinal": observed}
        else:
            continue
        row = turns.setdefault(key, {**identity, "status": "open",
                                     "first_seq": record["seq"],
                                     "last_seq": record["seq"]})
        row["last_seq"] = record["seq"]
        if event["type"] == "turn.ended":
            row["status"] = (event.get("payload") or {}).get("status", "ended")
    return [turns[key] for key in sorted(turns)]


class ReadFacade:
    """只读会话查询 facade；store 只需提供 session/read 两个方法。"""

    def __init__(self, store):
        self.store = store

    def session(self, session_id, *, tail=None, before=None):
        meta = self.store.session(session_id)
        if meta is None:
            return None
        return project_session(session_id, meta["agent"], self.store.read(session_id),
                               tail=tail, before=before)

    def usage(self, session_id):
        return summarize_usage(self.store.read(session_id))

    def usage_audit(self, session_id):
        return audit_usage(self.store.read(session_id))

    def tools(self, session_id, status=None, name=None):
        return list_tools(self.store.read(session_id), status, name)

    def tool_stats(self, session_id):
        return summarize_tools(self.store.read(session_id))

    def timing(self, session_id):
        return summarize_timing(self.store.read(session_id))

    def compactions(self, session_id):
        return list_compactions(self.store.read(session_id))


SessionQueries = ReadFacade

__all__ = [
    "ReadFacade", "SessionQueries", "audit_usage", "list_compactions", "list_tools",
    "list_runs", "list_turns", "run_detail", "project_session", "summarize_timing",
    "summarize_tools", "summarize_usage", "tail_preview",
]


def session(store, session_id, *, tail=None, before=None):
    return ReadFacade(store).session(session_id, tail=tail, before=before)


def usage(store, session_id):
    return ReadFacade(store).usage(session_id)


def tools(store, session_id, status=None, name=None):
    return ReadFacade(store).tools(session_id, status, name)


def tool_stats(store, session_id):
    return ReadFacade(store).tool_stats(session_id)


def timing(store, session_id):
    return ReadFacade(store).timing(session_id)


def compactions(store, session_id):
    return ReadFacade(store).compactions(session_id)
