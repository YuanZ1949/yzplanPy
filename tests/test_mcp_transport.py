"""MCP HTTP/SSE 传输层回归测试（D1 + D2 双重失效修复）。

D1：main.py 曾以 `lambda e, s: mcp_server._http_handler(e, s, {})` 启动 HTTP 服务，
    `{}` 在 lambda 体内每次调用新建 → POST /messages 的响应写入立即丢弃的 dict，
    GET /messages 永远空队列 → 恒返回 {"result": {}}。
    修复：session_state 提到闭包外共享（make_http_handler 工厂）。
D2：transport.py `_events()` 只发 endpoint+initialized+keep-alive，从不读
    session_state 推响应 → SSE 通道"半残"。
    修复：_events 轮询 session_state 队列并推送挂起响应。
D3：`/sse` 手写 `Connection: keep-alive` hop-by-hop 响应头，wsgiref
    start_response 断言拒绝 → 每次 SSE 连接 500。
    修复：删除该头（HTTP/1.1 默认持久）。

测试隔离：直接调用 _http_handler / make_http_handler，不依赖真实端口；
D3 例外——必须起真实 wsgiref 服务器才能触发 start_response 断言。
"""

import json
import re
from typing import Iterator, cast


class _Input:
    """最小 wsgi.input 替身。"""

    def __init__(self, data: bytes):
        self._data = data

    def read(self, _n: int = -1) -> bytes:
        return self._data


def _env(path, method="GET", query="", body=b""):
    return {
        "PATH_INFO": path,
        "REQUEST_METHOD": method,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "HTTP_HOST": "127.0.0.1:8765",
        "wsgi.input": _Input(body),
    }


def _start_response(_status, _headers):
    pass


def _json_body(resp):
    """从 _as_json 返回的 [bytes] 中解析 JSON。"""
    return json.loads(resp[0].decode("utf-8"))


# ── D1：session_state 必须跨请求共享 ──────────────────────────────────

def test_http_handler_shares_session_state_across_requests():
    """D1 回归：POST /messages 存入的响应必须能被后续 GET /messages 取回。

    修复前 main.py 每次调用都新建 `{}`，POST 写入的 dict 立即丢弃，
    GET 永远读到空队列 → 恒返回 {"result": {}}。
    """
    from mcp_server.transport import make_http_handler

    handler = make_http_handler()
    body = b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}'
    handler(_env("/messages", "POST", "session_id=s1", body), _start_response)

    resp = handler(_env("/messages", "GET", "session_id=s1"), _start_response)
    payload = _json_body(resp)
    assert payload["id"] == 1
    assert payload["result"] == {}


def test_http_handler_shared_state_keeps_multiple_responses():
    """D1 补充：共享 session_state 下多个响应按序入队、按序取回。"""
    from mcp_server.transport import make_http_handler

    handler = make_http_handler()
    for i in (1, 2):
        body = json.dumps({"jsonrpc": "2.0", "id": i, "method": "ping"}).encode()
        handler(_env("/messages", "POST", "session_id=s2", body), _start_response)

    first = _json_body(handler(_env("/messages", "GET", "session_id=s2"), _start_response))
    second = _json_body(handler(_env("/messages", "GET", "session_id=s2"), _start_response))
    assert [first["id"], second["id"]] == [1, 2]


# ── D2：SSE _events 必须推送挂起响应 ──────────────────────────────────

def test_sse_events_pushes_pending_responses():
    """D2 回归：POST /messages 后，SSE 通道必须推送该响应（而非只发 keep-alive）。"""
    from mcp_server.transport import _http_handler

    session_state = {}
    # WSGI 应用必须产出 bytes（D3 修复后 _http_handler 遵守该契约），测试侧解码回 str 断言
    gen = cast(Iterator[bytes], _http_handler(_env("/sse"), _start_response, session_state))

    endpoint = next(gen).decode("utf-8")
    assert "event: endpoint" in endpoint
    m = re.search(r"session_id=([0-9a-f]+)", endpoint)
    assert m, "endpoint 事件必须携带 session_id"
    sid = m.group(1)
    next(gen)  # notifications/initialized

    # POST 一个 ping → 响应进入 session_state[sid]
    body = b'{"jsonrpc": "2.0", "id": 7, "method": "ping"}'
    _http_handler(_env("/messages", "POST", f"session_id={sid}", body),
                  _start_response, session_state)

    # SSE 通道应推送该响应
    event = next(gen).decode("utf-8")
    assert "event: message" in event, f"SSE 应推送 message 事件，实际: {event!r}"
    assert '"id": 7' in event
    assert '"result": {}' in event


# ── D3：/sse 响应头不得含 hop-by-hop 头（真实 wsgiref 路径） ────────────

def test_sse_endpoint_no_hop_by_hop_headers_via_wsgiref():
    """D3 回归：GET /sse 必须走通真实 wsgiref 服务器并返回 200。

    transport.py 曾手写 `Connection: keep-alive` 响应头，而 stdlib wsgiref 的
    `start_response` 断言 hop-by-hop 头非法 → 每次 SSE 连接必 500
    （实测 data/logs/stderr.log 2026-10-06 21:02:53 AssertionError，
    栈落 mcp_server/transport.py:96）。旧测试的 stub `_start_response`
    不做校验，拦不住 —— 本测试必须走真实 wsgiref。
    """
    import http.client
    import threading
    from wsgiref.simple_server import make_server

    from mcp_server.transport import make_http_handler

    real = make_http_handler()

    def app(env, sr):
        """真实 handler + 截断 SSE 无限流（测试服务器是单线程，流不截断会卡死收尾）。"""
        result = real(env, sr)
        if env.get("PATH_INFO", "").startswith("/sse"):
            def _limited():
                for i, chunk in enumerate(result):
                    yield chunk
                    if i >= 2:      # endpoint + initialized + 首个 keep-alive 即够
                        return
            return _limited()
        return result

    server = make_server("127.0.0.1", 0, app)
    server.handle_error = lambda req, addr: None  # 静默客户端提前断开的写失败
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        conn.request("GET", "/sse")
        resp = conn.getresponse()
        status = resp.status
        conn.close()
        assert status == 200, (
            f"GET /sse 返回 {status}（wsgiref 拒绝 hop-by-hop 响应头？）"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "wsgiref 服务器未能在 5s 内停止"