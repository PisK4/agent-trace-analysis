"""会话元事实折叠（架构评审候选 4）。

「latest-wins、用户改名后 opened 不再覆盖」的标题规则此前同时活在三处：
ledger._append_locked 的索引维护、project_session 的投影重推、droid 的
标题补写注释。这里给出唯一纯函数定义；账本索引维护调用它，投影层
project_session 的独立重推与之互为对照（两侧对同一事件流必须产出同题）。
"""
REAL_TS_FLOOR = 10 ** 12


def fold_session_meta(existing, event):
    """existing: 折叠态 dict（含 title/renamed/turns/last_ts/first_ts/
    parent_session_id）或 None（新会话）。event: 已解析的事件 dict。
    返回新的折叠态 dict（不改入参）。"""
    row = dict(existing) if existing else {
        "title": event.get("session_id") or "",
        "renamed": False,
        "turns": 0,
        "last_ts": 0,
        "first_ts": 0,
        "parent_session_id": None,
    }
    # existing 允许只带部分键（调用方可能从行记录挑字段组装），缺省按折叠初值。
    row.setdefault("renamed", False)
    row.setdefault("turns", 0)
    row.setdefault("last_ts", 0)
    row.setdefault("first_ts", 0)
    ts = int(event.get("ts") or 0)
    row["last_ts"] = max(int(row["last_ts"] or 0), ts)
    # 创建时间取最早的真实事件 ts；异常小值（如 1，历史推送端写过 ts=1 的
    # opened 事件）不参与，避免显示成 1970 年，存量异常值也一并设防。
    incoming_first = ts if ts > REAL_TS_FLOOR else 0
    if int(row["first_ts"] or 0) > REAL_TS_FLOOR:
        row["first_ts"] = min(int(row["first_ts"]), incoming_first) if incoming_first else row["first_ts"]
    else:
        row["first_ts"] = incoming_first
    typ = event.get("type")
    p = event.get("payload") or {}
    if typ == "session.opened":
        # 用户改过名后 opened 只做兜底，不再覆盖（投影层同规则）
        if not row["renamed"]:
            row["title"] = p.get("title") or row["title"]
        # 非 opened 事件必须保留已有父引用；opened 不带 parent 时也不能把
        # 已有血缘抹成 NULL。
        if p.get("parent_session"):
            row["parent_session_id"] = p["parent_session"]
    elif typ == "session.renamed":
        # 用户改名：latest-wins，后续 opened 不再覆盖
        row["title"] = p.get("title") or row["title"]
        row["renamed"] = True
    turn = event.get("turn")
    if isinstance(turn, int) and turn > row["turns"]:
        row["turns"] = turn
    return row
