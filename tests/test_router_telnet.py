"""router_admin 传输层测试：假 socket 离线跑，绝不连 192.0.2.1 以外的任何真实地址。

192.0.2.0/24 是 RFC 5737 保留的文档用网段；这里只作为「配置串」出现，
所有收发都由 FakeSocket 模拟，不发生任何真实 socket 行为。
"""
import re
import socket
import time
from collections import deque

import pytest

from modules.router_admin import telnet as t

BANNER = b"XiaoQiang login: "
PASSWORD_PROMPT = b"Password: "
PROMPT = b"root@XiaoQiang:~# "

# BusyBox MOTD：刻意含大量 '#' 与假提示符片段，任何「读到 # 就停」的判据都会误判
MOTD = (
    b"\r\n"
    b"        /     \\  _     _   _  _    _    ___\r\n"
    b"       |       || |   | | | || |  / _ \\\r\n"
    b"       |   _   || |___| |_| || || | | | |_ \r\n"
    b"       |  |_|  ||  ___  _  || || |_| |  _|\r\n"
    b"       |       || |   | | | || |  ___ | |\r\n"
    b"       \\_____/ ||_|   |_| |_||_||____/|_|\r\n"
    b"                      ____ _   _____   ____\r\n"
    b"  ############################################\r\n"
    b"  #  BusyBox v1.25.1 (2024-01-01 00:00:00 UTC) #\r\n"
    b"  ############################################\r\n"
    b"  press Enter to activate root@XiaoQiang:~#\r\n"
)

MARKER_RE = re.compile(r"__YZP_[0-9a-f]{8}__")
#: bytes 版：FakeSocket 内部按原始字节做子串匹配，只能用 bytes 模式
MARKER_BYTES_RE = re.compile(rb"__YZP_[0-9a-f]{8}__")


#: 真机 tty 的折行列宽。回显超过该列数就插入 CR LF，把回显（可能连结束标记
#: 本身）从中间切开 —— 断点位置随命令长度漂移。
ECHO_WRAP_COLS = 80


def _wrap_echo(echo, cols):
    """模拟真机 tty 折行：逐列输出，超出 `cols` 就折行，续行以一个前导空格起头。

    续行空格属于**续行那一行**的开头（真机实测 `; echo\\r\\n __YZP_1469c199__`），
    不是上一行的结尾 —— 否则会凭空造出一行只含空格的行。
    """
    if not cols or len(echo) <= cols:
        return echo
    out = bytearray()
    line = bytearray()
    for ch in echo:
        if not line:
            line.append(0x20)                   # 续行前导空格
        line.append(ch)
        if len(line) >= cols:
            out += line + b"\r\n"
            line.clear()
    if line:
        out += line
    return bytes(out)


class FakeSocket:
    """socket.socket 的离线替身。

    script 元素为 (trigger, resp)：
      - trigger 为 None → 下一次 recv 立即返回；
      - trigger 为 bytes → 仅当「已发送内容」包含它时才返回（模拟对端收到命令后回应）。
    resp 可以是：
      - bytes            —— 一次 recv 返回；
      - list[bytes]      —— 分多次 recv 返回（制造「结束标记被拆包」）；
      - Exception 实例   —— recv 抛出（断链）。
    echo=True 时把「已发送但尚未回显」的内容前缀进响应，模拟 tty 回显；
    echo_wrap 为正整数时按该列宽折行回显，模拟真机 tty 把回显（可能连结束标记
    本身）从中间切开（缺省 0=不折行，既有测试不受影响）；
    on_exhausted="junk" 时脚本耗尽后继续返回噪声（用于走真实超时截止逻辑）。
    """

    def __init__(self, script, echo=True, on_exhausted="timeout", echo_wrap=0):
        self.script = list(script)
        self.echo = echo
        self.on_exhausted = on_exhausted
        self.echo_wrap = echo_wrap
        self.sent = bytearray()
        self.settimeouts = []
        self.sockopts = []
        self.connected_to = None
        self.closed = False
        self.connect_error = None
        self.recv_count = 0
        self._queue = deque()
        self._echo_pos = 0

    # ── socket 接口 ──
    def settimeout(self, value):
        self.settimeouts.append(value)

    def setsockopt(self, level, opt, value):
        self.sockopts.append((level, opt, value))

    def connect(self, addr):
        self.connected_to = addr
        if self.connect_error:
            raise self.connect_error

    def sendall(self, data):
        if self.closed:
            raise OSError("send on closed socket")
        self.sent.extend(data)

    def _matchable(self):
        """已发送内容去掉结束标记后的副本 —— 匹配 trigger 只看这个。

        `run()` 每条命令都会追加一个随机 8 位十六进制的结束标记
        （`__YZP_a40fc335__`），十六进制串里完全可能出现 `c3` / `c1` 这类
        字节对。直接拿累积的原始 sent 做子串匹配就会假性命中下一条命令的
        脚本项，让 run_batch 偶发串位（实测 200 次里错 14 次）。
        """
        return MARKER_BYTES_RE.sub(b"", bytes(self.sent))

    def recv(self, n):
        self.recv_count += 1
        if not self._queue:
            matchable = self._matchable()
            for i, (trigger, resp) in enumerate(self.script):
                if trigger is None or trigger in matchable:
                    del self.script[i]
                    if isinstance(resp, list):
                        self._queue.extend(resp)
                    else:
                        self._queue.append(resp)
                    break
        if not self._queue:
            if self.on_exhausted == "junk":
                return b"\r\njunk "
            raise socket.timeout("fake: 脚本已耗尽")
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        if not item:
            return b""
        if self.echo:
            echo = bytes(self.sent[self._echo_pos:]).replace(b"\n", b"\r\n")
            self._echo_pos = len(self.sent)
            item = _wrap_echo(echo, self.echo_wrap) + item
        return item

    def close(self):
        self.closed = True

    # ── 断言辅助 ──
    def sent_text(self):
        return self.sent.decode("utf-8", "replace")

    def markers(self):
        """从已发送内容里抽出全部结束标记，验证同会话内不重复。"""
        return MARKER_RE.findall(self.sent_text())


# ── FakeSocket 自身的行为（它一旦失真，上面所有测试都不可信）─────

def test_FakeSocket_随机marker的十六进制不误触发下一条命令():
    """回归：`__YZP_a40fc335__` 的 hex 里含字节对 `c3`。

    若按累积的原始 sent 做子串匹配，这条命令会假性命中 trigger 为 `c3` 的
    脚本项，把下一条命令的回复提前吃掉 —— 表现为 run_batch 偶发返回
    `['one', 'three', '']`（实测 200 次里错 14 次）。
    """
    script = [
        (b"c1", _reply(b"__YZP_11111111__", b"one")),
        (b"c3", _reply(b"__YZP_33333333__", b"three")),
    ]
    fake = FakeSocket(script)
    fake.connect(("192.0.2.1", 23))
    # 先吃掉 c1，模拟 run_batch 里前一条命令已正常完成
    fake.sendall(b"c1; echo __YZP_11111111__\n")
    assert b"one" in fake.recv(4096)
    # 这条命令的 marker hex 恰好含 "c3"，但对端对它没有任何回复
    fake.sendall(b"c2; echo __YZP_a40fc335__\n")
    with pytest.raises(socket.timeout):
        fake.recv(4096)
    # c3 的回复必须还在脚本里等着，不能被上一条命令偷吃
    assert [trigger for trigger, _ in fake.script] == [b"c3"]


def test_FakeSocket_仍然能按命令文本匹配到脚本项():
    """反向确认：遮蔽 marker 没有把正常匹配也一起废掉。"""
    script = [(b"c3", _reply(b"__YZP_33333333__", b"three"))]
    fake = FakeSocket(script)
    fake.connect(("192.0.2.1", 23))
    fake.sendall(b"c3; echo __YZP_44444444__\n")
    assert b"three" in fake.recv(4096)


def _login_script(extra=()):
    return [
        (None, BANNER),
        (b"root\n", PASSWORD_PROMPT),
        (b"secret\n", MOTD + PROMPT),
    ] + list(extra)


def _session(script, echo=True, on_exhausted="timeout", echo_wrap=0, **kwargs):
    fake = FakeSocket(script, echo=echo, on_exhausted=on_exhausted, echo_wrap=echo_wrap)
    opts = {"user": "root", "password": "secret", "socket_factory": lambda: fake}
    opts.update(kwargs)
    return t.TelnetSession("192.0.2.1", 23, **opts), fake


def _reply(marker, output=b""):
    """标准的一次命令响应：命令输出 + 结束标记行 + 新提示符（回显由 FakeSocket 前缀）。"""
    return output + b"\r\n" + marker + b"\r\n" + PROMPT


# ── 登录 ────────────────────────────────────────────────────────

def test_open_完成登录序列():
    s, fake = _session(_login_script())
    s.open()
    text = fake.sent_text()
    assert "root" in text and "secret" in text
    assert fake.connected_to == ("192.0.2.1", 23)
    assert s.connected is True
    s.close()


def test_open_先发用户名再发口令():
    s, fake = _session(_login_script())
    s.open()
    assert fake.sent_text().index("root") < fake.sent_text().index("secret")
    s.close()


def test_open_容忍MOTD里的井号():
    """MOTD 里有 #### 行与假提示符片段，就绪判定必须等真提示符。"""
    s, fake = _session(_login_script())
    s.open()
    # 登录后就绪后，残留缓冲里不应再有 MOTD 文本（否则会串进下一条命令输出）
    assert "BusyBox" not in s._text()[s._cut:]
    s.close()


def test_open_重复调用幂等():
    s, fake = _session(_login_script())
    s.open()
    s.open()
    s.close()


def test_open_无login提示抛超时异常():
    s, fake = _session([(None, b"nothing useful here\r\n")])
    with pytest.raises(t.TelnetTimeoutError):
        s.open()
    assert s.connected is False


def test_open_认证失败抛TelnetLoginError():
    s, fake = _session([
        (None, BANNER),
        (b"root\n", PASSWORD_PROMPT),
        (b"secret\n", b"\r\nLogin incorrect\r\n" + BANNER),
    ])
    with pytest.raises(t.TelnetLoginError) as ei:
        s.open()
    assert not isinstance(ei.value, t.TelnetTimeoutError)
    assert isinstance(ei.value, t.TelnetError)
    assert fake.closed is True


def test_open_认证失败不重试口令():
    s, fake = _session([
        (None, BANNER),
        (b"root\n", PASSWORD_PROMPT),
        (b"secret\n", b"Login incorrect\r\n" + BANNER),
        (b"secret\n", b"Login incorrect\r\n" + BANNER),
    ])
    with pytest.raises(t.TelnetLoginError):
        s.open()
    assert fake.sent_text().count("secret") == 1


def test_open_连接被拒抛TelnetConnectError():
    fake = FakeSocket([])
    fake.connect_error = ConnectionRefusedError("connection refused")
    s = t.TelnetSession("192.0.2.1", 23, socket_factory=lambda: fake)
    with pytest.raises(t.TelnetConnectError):
        s.open()
    assert fake.connected_to == ("192.0.2.1", 23)
    assert fake.closed is True


# ── run ─────────────────────────────────────────────────────────

def test_run_返回命令输出():
    s, fake = _session(_login_script([(b"uptime", _reply(b"__YZP_aaaaaaaa__", b"uptime output"))]))
    s.open()
    out = s.run("uptime")
    assert "uptime output" in out
    s.close()


def test_run_剔除结束标记():
    s, fake = _session(_login_script([(b"uptime", _reply(b"__YZP_aaaaaaaa__", b"uptime output"))]))
    s.open()
    out = s.run("uptime")
    assert "__YZP_" not in out
    assert [ln for ln in out.splitlines() if "__YZP_" in ln] == []
    s.close()


def test_run_剔除提示符与回显行():
    s, fake = _session(_login_script([(b"uptime", _reply(b"__YZP_aaaaaaaa__", b"uptime output"))]))
    s.open()
    out = s.run("uptime")
    assert "root@XiaoQiang" not in out
    assert "echo __YZP_" not in out
    assert out.strip() == "uptime output"
    s.close()


def test_run_标记被拆包也能识别():
    """结束标记跨两个 TCP 包到达时也必须能收敛。"""
    script = _login_script([
        (b"uptime", [b"part1\r\n__YZP_0123ab", b"cd__\r\n" + PROMPT]),
    ])
    s, fake = _session(script)
    s.open()
    out = s.run("uptime")
    assert "part1" in out
    assert "__YZP_" not in out
    s.close()


def test_run_过滤IAC字节():
    iac = (b"\xff\xfb\x18\xff\xfb\x01"          # WILL TERMINAL-TYPE / WILL ECHO
           b"\xff\xfa\x18\x00\xff\xf0"          # SB ... IAC SE
           b"clean text\r\n__YZP_aaaaaaaa__\r\n" + PROMPT)
    s, fake = _session(_login_script([(b"uptime", iac)]))
    s.open()
    out = s.run("uptime")
    assert "\xff" not in out and "\xfa" not in out
    assert out.strip() == "clean text"
    s.close()


def test_run_两条命令输出不串扰():
    script = _login_script([
        (b"uptime", _reply(b"__YZP_aaaaaaaa__", b"A-OUTPUT")),
        (b"loadavg", _reply(b"__YZP_bbbbbbbb__", b"B-OUTPUT")),
    ])
    s, fake = _session(script)
    s.open()
    a = s.run("uptime")
    b = s.run("loadavg")
    assert "A-OUTPUT" in a and "B-OUTPUT" not in a
    assert "B-OUTPUT" in b and "A-OUTPUT" not in b
    s.close()


@pytest.mark.parametrize("cols", list(range(40, 100)))
def test_run_回显在任意列折行都能剔除(cols):
    """真机回归：tty 在固定列宽（实测 80）折行，断点随命令长度漂移。

    真机上换行可能落在 `; echo ` 之后，也可能**落在结束标记内部**（实测
    `; echo __YZP_` + 换行 + `1469c199__`），甚至落在提示符与命令之间。结果是
    `root@XiaoQiang:~# <整条命令>` 整段泄漏进返回值：

      - 提示符残片会让 `parse_uptime_fmt` 之类的解析器读到脏数据；
      - `__YZP_xxxxxxxx__` 全由下划线与十六进制组成，能通过
        `services.SERVICE_NAME_RE`，被当成一个真服务混进服务列表。

    所以这里扫遍 40~99 列，确保「; echo 」/ 标记内部 / 标记之后 三类断点
    都被剔除干净 —— 实现必须容忍回显中**任意位置**插入空白。
    """
    cmd = "for f in /etc/init.d/*; do basename $f; done 2>/dev/null"
    script = _login_script([
        (b"basename $f", _reply(b"__YZP_aaaaaaaa__", b"auto_speedtest\nnetwork\ntelnet")),
    ])
    s, fake = _session(script, echo_wrap=cols)
    s.open()
    out = s.run(cmd)
    assert "__YZP_" not in out                       # 标记（含被切开的两半）不得泄漏
    assert "basename" not in out                     # 回显残片不得泄漏
    assert "2>/dev/null" not in out
    assert "XiaoQiang" not in out                    # 提示符残片不得泄漏
    assert out.splitlines() == ["auto_speedtest", "network", "telnet"]
    s.close()


def test_run_回显被折行切开时仍能剔除():
    """真机原始故障：折行断点恰好落在 `; echo ` 之后。"""
    cmd = "for f in /etc/init.d/*; do basename $f; done 2>/dev/null"
    script = _login_script([
        (b"basename $f", _reply(b"__YZP_aaaaaaaa__", b"auto_speedtest\nnetwork\ntelnet")),
    ])
    s, fake = _session(script, echo_wrap=ECHO_WRAP_COLS)
    s.open()
    out = s.run(cmd)
    assert "__YZP_" not in out
    assert out.splitlines() == ["auto_speedtest", "network", "telnet"]
    s.close()


def test_run_无回显时也能工作():
    script = _login_script([
        (b"uptime", b"uptime output\r\n__YZP_aaaaaaaa__\r\n" + PROMPT),
    ])
    s, fake = _session(script, echo=False)
    s.open()
    out = s.run("uptime")
    assert out.strip() == "uptime output"
    s.close()


def test_run_每条命令用不同结束标记():
    script = _login_script([
        (b"cmdA", _reply(b"__YZP_aaaaaaaa__")),
        (b"cmdB", _reply(b"__YZP_bbbbbbbb__")),
    ])
    s, fake = _session(script)
    s.open()
    s.run("cmdA")
    s.run("cmdB")
    markers = fake.markers()
    assert len(markers) == 2
    assert markers[0] != markers[1]
    s.close()


def test_run_发送内容含结束标记():
    s, fake = _session(_login_script())
    s.open()
    with pytest.raises(t.TelnetTimeoutError):
        s.run("echo hello")
    assert "echo hello; echo __YZP_" in fake.sent_text()
    s.close()


def test_run_无响应抛TelnetTimeoutError():
    s, fake = _session(_login_script())
    s.open()
    with pytest.raises(t.TelnetTimeoutError):
        s.run("sleep 999")
    s.close()


def test_run_超时会走真实截止逻辑():
    """脚本耗尽但对端持续吐噪声：必须按 timeout 秒真实截止，而不是死循环。"""
    s, fake = _session(_login_script(), on_exhausted="junk")
    s.open()
    t0 = time.monotonic()
    with pytest.raises(t.TelnetTimeoutError):
        s.run("sleep 999", timeout=0.3)
    elapsed = time.monotonic() - t0
    assert 0.2 <= elapsed < 5.0
    s.close()


def test_run_超时后继续使用会话():
    """一次超时不等于断链（路由器忙），会话应仍可继续跑下一条。"""
    script = _login_script([(b"fast", _reply(b"__YZP_aaaaaaaa__", b"FAST"))])
    s, fake = _session(script)
    s.open()
    with pytest.raises(t.TelnetTimeoutError):
        s.run("slowcmd-not-in-script")
    out = s.run("fast")
    assert "FAST" in out
    assert "slowcmd" not in out
    s.close()


def test_run_对端关闭抛TelnetError():
    script = _login_script([(b"uptime", b"")])
    s, fake = _session(script)
    s.open()
    with pytest.raises(t.TelnetError):
        s.run("uptime")
    s.close()


def test_run_未打开时抛TelnetError():
    s, fake = _session(_login_script())
    with pytest.raises(t.TelnetError):
        s.run("uptime")


def test_run_默认使用read_timeout():
    s, fake = _session(_login_script(), read_timeout=7.5)
    s.open()
    with pytest.raises(t.TelnetTimeoutError):
        s.run("nothing-in-script")
    # 单次 recv 的超时不得超出 read_timeout（connect 阶段用 connect_timeout=8.0）
    assert all(0 < v <= 7.5 for v in fake.settimeouts[1:])
    s.close()


# ── run_batch ───────────────────────────────────────────────────

def test_run_batch_按顺序返回等长列表():
    script = _login_script([
        (b"c1", _reply(b"__YZP_11111111__", b"one")),
        (b"c2", _reply(b"__YZP_22222222__", b"two")),
        (b"c3", _reply(b"__YZP_33333333__", b"three")),
    ])
    s, fake = _session(script)
    s.open()
    got = s.run_batch(["c1", "c2", "c3"])
    assert len(got) == 3
    assert "one" in got[0] and "two" in got[1] and "three" in got[2]
    assert all("__YZP_" not in g for g in got)
    s.close()


def test_run_batch_一次连接内复用同一socket():
    script = _login_script([(b"c1", _reply(b"__YZP_11111111__", b"one"))])
    s, fake = _session(script)
    s.open()
    s.run_batch(["c1", "c1"])
    assert len(fake.markers()) == 2
    s.close()


def test_run_batch_空输入返回空列表():
    s, fake = _session(_login_script())
    s.open()
    assert s.run_batch([]) == []
    s.close()


def test_run_batch_单条失败返回空串且不中断整批():
    script = _login_script([
        (b"c1", _reply(b"__YZP_11111111__", b"one")),
        (b"c3", _reply(b"__YZP_33333333__", b"three")),
    ])
    s, fake = _session(script)
    s.open()
    got = s.run_batch(["c1", "c2-missing", "c3"])
    assert len(got) == 3
    assert "one" in got[0]
    assert got[1] == ""
    assert "three" in got[2]
    s.close()


def test_run_batch_断链后剩余条目为空串():
    script = _login_script([
        (b"c1", _reply(b"__YZP_11111111__", b"one")),
        (b"c2", ConnectionResetError("connection reset by peer")),
        (b"c3", _reply(b"__YZP_33333333__", b"three")),
    ])
    s, fake = _session(script)
    s.open()
    got = s.run_batch(["c1", "c2", "c3"])
    assert len(got) == 3
    assert "one" in got[0]
    assert got[1] == ""
    assert got[2] == ""
    s.close()


def test_run_batch_单条输出不泄漏给下一条():
    script = _login_script([
        (b"c1", _reply(b"__YZP_11111111__", b"ONLY-ONE")),
        (b"c2", _reply(b"__YZP_22222222__", b"ONLY-TWO")),
    ])
    s, fake = _session(script)
    s.open()
    first, second = s.run_batch(["c1", "c2"])
    assert "ONLY-ONE" in first and "ONLY-ONE" not in second
    assert "ONLY-TWO" in second and "ONLY-TWO" not in first
    s.close()


# ── close / 上下文管理器 ────────────────────────────────────────

def test_close_幂等():
    s, fake = _session(_login_script())
    s.open()
    s.close()
    s.close()
    s.close()
    assert fake.closed is True
    assert s.connected is False


def test_close_未打开不报错():
    s, fake = _session(_login_script())
    s.close()
    assert s.connected is False


def test_close_设置SO_LINGER():
    s, fake = _session(_login_script())
    s.open()
    s.close()
    assert fake.sockopts
    level, opt, _value = fake.sockopts[-1]
    assert opt == socket.SO_LINGER
    assert level == socket.SOL_SOCKET


def test_with_语句自动关闭():
    script = _login_script([(b"c1", _reply(b"__YZP_11111111__", b"x"))])
    fake = FakeSocket(script)
    with t.TelnetSession("192.0.2.1", 23, user="root", password="secret",
                         socket_factory=lambda: fake) as s:
        assert s.connected is True
        assert "x" in s.run("c1")
    assert fake.closed is True


def test_with_语句体内异常仍关闭():
    fake = FakeSocket(_login_script())
    with pytest.raises(RuntimeError):
        with t.TelnetSession("192.0.2.1", 23, user="root", password="secret",
                             socket_factory=lambda: fake):
            raise RuntimeError("boom")
    assert fake.closed is True


# ── 解码器 ──────────────────────────────────────────────────────

def test_decode_telnet_丢弃协商序列():
    assert t.decode_telnet(b"\xff\xfb\x01\xff\xfc\x01hello\xff\xfd\x03world") == "helloworld"


def test_decode_telnet_丢弃子协商块():
    raw = b"a\xff\xfa\x18\x00\xff\xf0b\xff\xfa\x1f\x00\x01\xff\xf0c"
    assert t.decode_telnet(raw) == "abc"


def test_decode_telnet_保留换行并归一CRLF():
    assert t.decode_telnet(b"line1\r\nline2\n") == "line1\nline2\n"


def test_decode_telnet_连续FF不产生残留():
    assert t.decode_telnet(b"\xff\xff\xff") == ""


def test_decode_telnet_保留UTF8中文():
    assert t.decode_telnet("内存占用 42%".encode("utf-8")) == "内存占用 42%"


def test_decode_telnet_非法UTF8用替换字符():
    assert t.decode_telnet(b"ok\x80") == "ok\ufffd"


def test_decode_telnet_丢弃控制字符但保留制表符():
    assert t.decode_telnet(b"a\x00b\x07c\td") == "abc\td"


def test_decode_telnet_空输入():
    assert t.decode_telnet(b"") == ""
