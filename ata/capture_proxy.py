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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
_CHUNK = 65536
# 转发头黑名单（hop-by-hop）：其余头（含认证头）原样透传给上游——红线是
# 「认证头不落账本」而不是「不转发」，上游网关需要客户端的 key。
# record 的 request_headers 只收 x-claude-*，这是落档侧的那道闸。
_HOP_HEADERS = {"host", "content-length", "connection", "transfer-encoding"}


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
                "request_headers": {k: v for k, v in self.headers.items()
                                    if k.lower().startswith("x-claude")},
                "request_body": bytes(body),
                "response_content_type": content_type,
                "response_body": bytes(buf),
                "started_at_ms": int(started * 1000),
                "completed_at_ms": int(completed * 1000),
            }
            try:
                ingest(record)
            except Exception as exc:  # noqa: BLE001
                print(f"capture ingest error: {exc}")

        do_POST = _relay
        do_GET = _relay
        do_PUT = _relay
        do_DELETE = _relay
        do_PATCH = _relay

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((host, port), Handler)
