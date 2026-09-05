"""MCP 传输层：stdio 与 HTTP/SSE 两种传输方式。

与旧 mcp_server.py 的 run_stdio/_http_handler/_as_json/run_http 完全一致。
"""

import json
import sys
import time
import uuid

from .protocol import _log, handle_message, _make_error, _INTERNAL_ERROR_CODE


# ── stdio 传输 ────────────────────────────────────────────────────────

def run_stdio():
    """MCP stdio 传输：从 stdin 读取 JSON-RPC，写回 → stdout。"""
    import select
    _log("YZplan MCP stdio server 启动")
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle_message(msg)
        except Exception as e:  # noqa: BLE001
            _log("处理消息异常", e)
            resp = _make_error(msg.get("id") if isinstance(msg, dict) else None,
                               _INTERNAL_ERROR_CODE, f"服务内部错误: {e}")
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


# ── HTTP/SSE 传输 ─────────────────────────────────────────────────────

def _http_handler(env, start_response, session_state):
    from . import TOOLS  # 延迟导入：/tools 端点需要完整工具表
    from urllib.parse import parse_qs, urlparse
    path = env.get("PATH_INFO", "/")
    method = env.get("REQUEST_METHOD", "GET")
    query = parse_qs(env.get("QUERY_STRING", ""))
    length = int(env.get("CONTENT_LENGTH") or 0)
    body = env["wsgi.input"].read(length) if length else b""

    if path in ("/sse", "/sse?"):
        # Server-Sent Events：为客户端分配 session，发送初始端点
        sid = uuid.uuid4().hex
        url = f"http://{env.get('HTTP_HOST', '127.0.0.1:8765')}/messages?session_id={sid}"
        session_state[sid] = []

        def _events():
            yield f"event: endpoint\ndata: {url}\n\n"
            yield "event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\"}\n\n"
            # 长连接保持
            while True:
                yield ": keep-alive\n\n"
                time.sleep(15)

        start_response("200 OK", [("Content-Type", "text/event-stream"),
                                  ("Cache-Control", "no-cache"),
                                  ("Connection", "keep-alive")])
        return _events()

    if path == "/messages" and method == "POST":
        sid = (query.get("session_id") or [""])[0]
        try:
            msg = json.loads(body.decode("utf-8"))
        except Exception:
            return _as_json(start_response, {"error": "bad json"}, 400)
        resp = handle_message(msg)
        if resp is not None:
            # 简化：把响应塞进 session 队列（由客户端以 GET /messages 拉取或返回响应）
            session_state.setdefault(sid, []).append(resp)
            return _as_json(start_response, resp)
        return _as_json(start_response, {}, 202)

    if path == "/tools" and method == "GET":
        public_tools = [{k: v for k, v in t.items() if k != "handler"} for t in TOOLS]
        return _as_json(start_response, {"tools": public_tools})

    if path == "/messages" and method == "GET":
        sid = (query.get("session_id") or [""])[0]
        q = session_state.get(sid, [])
        resp = None
        if q:
            resp = q.pop(0)
        if resp is None:
            resp = {"jsonrpc": "2.0", "result": {}}
        return _as_json(start_response, resp)

    return _as_json(start_response, {"error": "not found"}, 404)


def _as_json(start_response, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    start_response(f"{status} OK", [("Content-Type", "application/json"),
                                    ("Content-Length", str(len(body)))])
    return [body]


def run_http(host="127.0.0.1", port=8765):
    from wsgiref.simple_server import make_server
    session_state = {}
    _log(f"YZplan MCP HTTP server 启动于 http://{host}:{port}")
    httpd = make_server(host, int(port), lambda e, s: _http_handler(e, s, session_state))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()