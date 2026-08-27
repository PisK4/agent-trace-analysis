"""转发式采集代理壳（架构评审候选 1 的「壳在 ata 重写」半边）。

职责只有三件：把 agent 的 LLM 流量原样转发给上游、把响应流式回传、
事后把截获的字节交给 ingest 翻译入账。ava 的对应壳住在 2158 行上帝
模块里且有三处已知脆弱点（locals().get 计时、writer 类属性侧信道、
frozen dataclass 贴 property），这里全部不复制：计时显式测量、ingest
显式注入、配置显式传参。

采集失败绝不弄挂被代理的请求：ingest 抛什么异常都吞掉打印。
"""
from __future__ import annotations

import http.client
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from ata.plugins.capture import resolve_session_id
from ata.wire.storage_headers import record_headers_for_storage

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
_CHUNK = 65536
# 转发头黑名单（hop-by-hop）：其余头（含认证头）原样透传给上游——红线是
# 「认证头不落账本」而不是「不转发」，上游网关需要客户端的 key。
# record 的 request_headers 只收 x-claude-*，这是落档侧的那道闸。
_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}

#: 哪些 wire 路径的请求走「虚拟 sid」兜底(代理壳不知道发起方是哪个
#: host——droid 真实流量既无 x-droid-* 头也无 body metadata.session_id,
#: 唯一可观察信号是 HTTP path)。 当前只覆盖 OpenAI Chat Completions /
#: Responses 两条(都是 droid / codex 走 OpenAI 协议用的 path 后缀)。
#:
#: 多 daemon 区分: 同一 client_port 短时间内(默认 5min) 复用同一虚拟 sid,
#: 不同的 daemon 各自用自己的 17878 连接(client port 不同) 拿不同虚拟
#: sid。 daemon 重连会让 client_port 变 → 新虚拟 sid, 这是设计取舍。
_VIRTUAL_SID_PATH_SUFFIXES = (
    "/v1/chat/completions", "/v1/responses")

#: 同一 client_port 复用虚拟 sid 的时间窗 (ms)。 5 分钟覆盖普通对话
#: 一轮的间隔, 超过此间隔视作"新 session"换新虚拟 sid。
_VIRTUAL_SID_WINDOW_MS = 5 * 60 * 1000


def _needs_virtual_sid(path: str) -> bool:
    """HTTP path 是否触发虚拟 sid 注入(剥离 query / 尾斜杠后比对)。"""
    normalized = (path or "").split("?", 1)[0].rstrip("/")
    return any(normalized.endswith(sfx) for sfx in _VIRTUAL_SID_PATH_SUFFIXES)

#: client_port → (virtual_sid, last_used_ms)。 进程内 dict, 多线程需加锁。
#: BaseHTTPRequestHandler 每个请求新建实例, state 必须放类外。
_virtual_sid_cache: dict[int, tuple[str, int]] = {}
_virtual_sid_lock = threading.Lock()


def _virtual_sid(agent_id, client_port, started_at_ms):
    """OpenAI 协议流量的兜底 sid, 按 client_port + 时间窗复用。

    同一 client_port 在 _VIRTUAL_SID_WINDOW_MS 内的所有 record 拿同一 sid,
    跨窗或新 client_port → 新 sid。 client_port 来自 droid/codex 客户端的
    17878 连接本地端口(每 daemon 实例不同), 这把多 daemon 实例区分开。
    """
    now_ms = int(started_at_ms)
    with _virtual_sid_lock:
        entry = _virtual_sid_cache.get(client_port)
        if entry is not None:
            cached_sid, last_ms = entry
            if now_ms - last_ms <= _VIRTUAL_SID_WINDOW_MS:
                _virtual_sid_cache[client_port] = (cached_sid, now_ms)
                return cached_sid
        sid = f"{agent_id}-wire-{client_port}-{uuid.uuid4().hex[:8]}"
        _virtual_sid_cache[client_port] = (sid, now_ms)
        return sid


def start_capture_proxy(host, port, upstream, agent_id, ingest):
    parts = urlsplit(upstream if "//" in upstream else f"https://{upstream}")
    secure = parts.scheme == "https"
    upstream_port = parts.port or (443 if secure else 80)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _relay(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            conn_cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
            conn = conn_cls(parts.hostname, upstream_port, timeout=600)
            started = time.time()
            completed = started
            content_type = ""
            buf = bytearray()
            try:
                # 除 hop-by-hop 外全量透传（认证头要能到上游网关）；
                # 留档侧另有白名单，x-api-key/authorization 不进 record。
                fwd = {k: v for k, v in self.headers.items()
                       if k.lower() not in _HOP_HEADERS}
                conn.request(self.command, self.path, body=body, headers=fwd)
                resp = conn.getresponse()
                content_type = resp.getheader("Content-Type") or ""
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() in _HOP_HEADERS:
                        continue
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    room = MAX_CAPTURE_BYTES - len(buf)
                    if room > 0:
                        buf.extend(chunk[:room])
                    self.wfile.write(f"{len(chunk):x}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except Exception as exc:
                print(f"capture proxy relay error: {exc}")
                try:
                    self.send_error(502, str(exc))
                except Exception:
                    pass
            finally:
                completed = time.time()
                conn.close()
            # 转发成功后才组 record；ingest 抛什么异常都不影响已回传的响应。
            if self.command != "POST":
                return
            record = {
                "agent_id": agent_id,
                "path": self.path.split("?", 1)[0],
                "request_headers": record_headers_for_storage(self.headers),
                "request_body": bytes(body),
                "response_content_type": content_type,
                "response_body": bytes(buf),
                "started_at_ms": int(started * 1000),
                "completed_at_ms": int(completed * 1000),
            }
            # droid/codex 等 agent 的真实 wire traffic 不带 sid (e2e 验证:
            # droid 既无 x-droid-* 头也无 body metadata.session_id; codex 也
            # 仅在 codex-via-cli 模式下有 metadata.session_id, 走代理时未必
            # 携带)。 代理壳按 path 后缀识别 OpenAI 协议流量, 给这些 record
            # 注入「虚拟 sid」兜底, 避免 ingest_capture 因拿不到 sid 整条吞掉。
            #
            # 多 daemon 区分: 虚拟 sid 含 client_port, 不同 droid CLI 实例
            # 各自用自己的 17878 连接 → 不同 client_port → 不同虚拟 sid。
            # 虚拟 sid 与 droid transcript 真 sid 不归并 — 后续时间窗归并是
            # 独立 todo(且 droid 一旦接 hook 通道, 这条兜底路径可退役)。
            if _needs_virtual_sid(record["path"]):
                sid = resolve_session_id(record, agent_id)
                if not sid:
                    record["session_id"] = _virtual_sid(
                        agent_id, self.client_address[1],
                        record["started_at_ms"])
            try:
                ingest(record)
            except Exception as exc:  # noqa: BLE001
                print(f"capture ingest error: {exc}", flush=True)

        do_POST = _relay
        do_GET = _relay
        do_PUT = _relay
        do_DELETE = _relay
        do_PATCH = _relay

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), Handler)
