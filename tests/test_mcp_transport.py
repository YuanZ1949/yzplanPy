"""MCP HTTP/SSE 传输层回归测试（D1 + D2 双重失效修复）。

D1：main.py 曾以 `lambda e, s: mcp_server._http_handler(e, s, {})` 启动 HTTP 服务，
    `{}` 在 lambda 体内每次调用新建 → POST /messages 的响应写入立即丢弃的 dict，
    GET /messages 永远空队列 → 恒返回 {"result": {}}。
    修复：session_state 提到闭包外共享（make_http_handler 工厂）。
D2：transport.py `_events()` 只发 endpoint+initialized+keep-alive，从不读
    session_state 推响应 → SSE 通道"半残"。
    修复：_events 轮询 session_state 队列并推送挂起响应。

测试隔离：直接调用 _http_handler / make_http_handler，不依赖真实端口。
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
    gen = cast(Iterator[str], _http_handler(_env("/sse"), _start_response, session_state))

    endpoint = next(gen)
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
    event = next(gen)
    assert "event: message" in event, f"SSE 应推送 message 事件，实际: {event!r}"
    assert '"id": 7' in event
    assert '"result": {}' in event