"""读取侧唯一 interface：HTTP 路由与 CLI 共用的派生口径。

权威层是 store.read 的裸事件流；便捷层投影的折叠实现都在 ata/project，
本模块只收口「HTTP 与 CLI 都要用的那部分」：Run/Turn 折叠、事件游标
分页、Evaluation 详情 join，以及投影函数的转发。分页口径只有这一份，
HTTP 与 CLI 各写一遍会静默漂移。
"""

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
    return [turns[key] for key in sorted(turns, key=lambda key: (key[0], key[1:]))]


def session_events(store, session_id, after=None, limit=None):
    """权威层游标分页：seq 严格大于 after 的事件 + 续读游标。

    after=None 表示从头读；limit=None 表示不截断。返回 (picked, next_after_seq)。
    """
    picked = [r for r in store.read(session_id)
              if after is None or r["seq"] > after]
    if limit is not None:
        picked = picked[:limit]
    return picked, (picked[-1]["seq"] if picked else (after or 0))


def evaluation_detail(ledger, state):
    """Evaluation 折叠态 + 成员会话 meta 与最新标注。

    标注仍是 Session fact：这里只读取每个成员 Session 的最新 score 供
    展示，不复制评分事实。state 为 None（unknown evaluation）原样返回。
    """
    if state is None:
        return None
    members = []
    for member in state["members"]:
        sid = member["session_id"]
        meta = ledger.session(sid)
        row = dict(member)
        if meta is not None:
            row["session"] = meta
            # 评分仍是 Session fact；Evaluation 只展示最新值，不复制事实。
            projected = project_session(sid, meta["agent"], ledger.read(sid))
            row["score"] = (projected.get("scores") or [None])[-1]
        members.append(row)
    return {**state, "members": members}


__all__ = [
    "audit_usage", "evaluation_detail", "list_compactions", "list_tools",
    "list_runs", "list_turns", "project_session", "run_detail",
    "session_events", "summarize_timing", "summarize_tools", "summarize_usage",
    "tail_preview",
]
