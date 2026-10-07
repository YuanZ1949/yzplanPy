"""登录握手录制与认证失败落盘（纯数据、无 Qt）。

用最小脚本化 socket 驱动真实 TelnetSession._login，验证接缝 set_exchange_hook
在成功/失败两条路径上的上报序列，以及 RecordingSession 的落盘与脱敏。

脚本化 socket 不模拟回显，也不需要 IAC：_login 只关心提示符与失败文案，逐块
喂入即足以驱动三阶段。
"""
import json
import socket
from collections import deque

import pytest

from modules.router_admin import telnet as t
from modules.router_admin.recorder import RecordingSession


class _ScriptedSocket:
    """按 recv 顺序吐预置响应块的最小 socket；无回显、无 IAC。"""

    def __init__(self, chunks):
        self._chunks = deque(chunks)
        self.sent = bytearray()
        self.closed = False

    def settimeout(self, value):
        pass

    def setsockopt(self, *a):
        pass

    def connect(self, addr):
        pass

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, n):
        if not self._chunks:
            raise socket.timeout("fake: 脚本已耗尽")
        return self._chunks.popleft()

    def close(self):
        self.closed = True


def _login_session(chunks, **kw):
    fake = _ScriptedSocket(chunks)
    opts = {"user": "root", "password": "s3cr3t", "socket_factory": lambda: fake}
    opts.update(kw)
    return t.TelnetSession("192.0.2.1", **opts)


# PROMPT_RE 要求提示符位于行首（re.M），故第三块前面必须带换行。
_SUCCESS = [b"XiaoQiang login: ", b"Password: ",
            b"\r\nBusyBox v1.30.1\r\n\r\nroot@XiaoQiang:~# "]
_FAIL = [b"XiaoQiang login: ", b"Password: ",
         b"\r\nLogin incorrect\r\n"]


def test_成功登录_上报五种事件():
    events = []
    s = _login_session(_SUCCESS)
    s.set_exchange_hook(events.append)
    s.open()
    assert [e["kind"] for e in events] == [
        "login_prompt", "username_sent", "password_prompt",
        "password_sent", "login_ok"]
    assert events[0]["recv"].endswith("login:")   # 截到提示符匹配末尾
    assert events[1]["send"] == "root"
    assert events[3]["send"] == "s3cr3t"          # 原样上报；脱敏在录制侧完成


def test_未装hook_登录行为零变化():
    s = _login_session(_SUCCESS)
    s.open()
    assert s.connected is True


def test_hook抛异常_登录不受影响():
    def boom(event):
        raise RuntimeError("录制坏了")

    s = _login_session(_SUCCESS)
    s.set_exchange_hook(boom)
    s.open()
    assert s.connected is True


def test_认证失败_抛TelnetLoginError且上报login_error():
    events = []
    s = _login_session(_FAIL)
    s.set_exchange_hook(events.append)
    with pytest.raises(t.TelnetLoginError):
        s.open()
    assert events[-1]["kind"] == "login_error"
    assert "incorrect" in events[-1]["recv"].lower()


def test_录制成功握手_落盘为v2且口令位脱敏(tmp_path):
    path = tmp_path / "rec.json"
    rec = RecordingSession(_login_session(_SUCCESS), str(path),
                           device="router-x", secrets=["s3cr3t"])
    rec.open()
    rec.close()
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["version"] == 2
    assert [s["kind"] for s in data["steps"]] == [
        "login_prompt", "username_sent", "password_prompt",
        "password_sent", "login_ok"]
    assert data["steps"][3]["send"] == "***"
    assert "s3cr3t" not in raw


def test_录制认证失败_落盘非空且含login_error(tmp_path):
    path = tmp_path / "rec.json"
    rec = RecordingSession(_login_session(_FAIL), str(path),
                           device="router-x", secrets=["s3cr3t"])
    with pytest.raises(t.TelnetLoginError):
        rec.open()
    rec.close()
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["steps"], "认证失败不能落成空文件"
    assert data["steps"][-1]["kind"] == "login_error"
    assert "s3cr3t" not in raw
