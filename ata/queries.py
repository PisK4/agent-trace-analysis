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


# 兼容更直观的类型名；查询实现仍只有一份。
SessionQueries = ReadFacade

__all__ = [
    "ReadFacade", "SessionQueries", "audit_usage", "list_compactions", "list_tools",
    "project_session", "summarize_timing", "summarize_tools", "summarize_usage",
    "tail_preview",
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
