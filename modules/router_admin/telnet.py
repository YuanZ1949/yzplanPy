"""router_admin 传输层：裸 socket telnet 会话（登录 / 执行命令 / 结束标记 / 关闭）。

规格：docs/superpowers/specs/2026-09-29-router-admin-design.md 第 5 节。要点：
- 纯 stdlib（requirements.txt 无 telnet 库），**不 import Qt**，便于离线单测；
- 每条命令追加 `; echo __YZP_<8位hex uuid>__` 作为结束标记，uuid 保证同会话内唯一，
  杜绝「上一条命令的残留输出被当成下一条结果」；
- 只过滤 IAC（0xFF）协议字节，不做协商应答（BusyBox telnetd 允许裸连接）；
- 异常分四类：连接失败 / 认证失败 / 超时 / 其它，调用方据此区分「口令错」与「路由器忙」；
- socket 由构造参数 socket_factory 注入（缺省走模块级 _create_socket），测试用假 socket 完全离线跑；登录提示/口令提示/shell 提示符均为宽松正则，BusyBox 变体也能命中。
"""
import logging
import re
import socket
import struct
import time
import uuid

_log = logging.getLogger(__name__)

MARKER_PREFIX = "__YZP_"
MARKER_SUFFIX = "__"
# 结束标记必须「独占一行」：tty 会回显我们发出的整条命令（里面也含标记串），
# 行锚定可把回显行排除在外。
MARKER_LINE_RE = re.compile(r"^__YZP_[0-9a-f]{8}__[ \t]*$", re.M)
# shell 提示符同样要求独占一行且行首无其它文字：BusyBox MOTD 里可能含
# `root@XiaoQiang:~#` 字样，只匹配行尾会被 MOTD 提前截断（假就绪）。
PROMPT_RE = re.compile(
    r"^[ \t]*root@[A-Za-z0-9_.\-]+:[^\n]*?[#$][ \t]*(?=\n|$)", re.M)

#: 回显折行时被 tty 插入的空白（换行 + 续行前导空格）
_ECHO_BREAK_WS = " \t\r\n"


def _match_lenient(head, sent, begin):
    """从 `head[begin:]` 起匹配 `sent`，允许中间插入任意空白。

    返回 `head` 中匹配结束（已跳过尾随空白）的下标；匹配不上返回 -1。

    关键在于**先消费、后跳空白**：若先跳空白再比对，`; echo ` 末尾那个真实空格会
    被当成「折行插入的空白」吃掉，随后拿 `_` 去比对空格而失配。折行只会*插入*
    空白、不会删改字符，所以逐字符「相同则消费，不同且为空白则跳过」既是精确匹配，
    又与断点位置无关。
    """
    global _LAST_FAIL
    _LAST_FAIL = None
    i = 0                    # 总是从头匹配 sent，begin 只决定 head 里的起点
    j = begin
    n, m = len(sent), len(head)
    while i < n:
        if j >= m:
            _LAST_FAIL = (i, j, "HEAD_EXHAUSTED", sent[max(0, i - 6):i + 6], head[max(0, j - 6):j + 6])
            return -1
        if head[j] == sent[i]:                   # 相同：先消费
            i += 1
            j += 1
            continue
        if head[j] in _ECHO_BREAK_WS:            # 不同：仅当是插入的空白才跳过
            j += 1
            continue
        return -1
    while j < m and head[j] in _ECHO_BREAK_WS:  # 跳过回显末尾的续行空格与换行
        j += 1
    return j


def _drop_leading_blank_lines(head, end):
    """返回 `head[end:]`，并吃掉开头那些「只含空白」的行。

    折行恰好落在回显末尾时，续行的前导空格会单独占一行
    （`…__YZP_xxx__\\r\\n \\r\\n<输出>`）。这类行是回显残留：命令真实输出不会以
    空白行开头，而调用方全是逐行解析的（parse_uci / parse_ifconfig / parse_arp …），
    删掉不影响任何内容。
    """
    while True:
        stop = head.find("\n", end)
        if stop < 0 or head[end:stop].strip():
            break
        end = stop + 1
    return head[end:]


def _strip_echo(head, sent):
    """剔除 tty 回显出来的「提示符 + 整条命令」，只留命令的真实输出。

    真机（小米 XiaoQiang）的 tty 会按固定列宽（实测 80）折行回显，**断点随命令
    长度漂移**：可能落在 `; echo ` 之后，也可能落在结束标记内部
    （`; echo __YZP_` + 换行 + `1469c199__`），还可能落在提示符与命令之间。所以
    任何「按固定子串查找回显尾端」的做法都会漏——实测后果是提示符残片与标记碎块
    整段泄漏进返回值，而 `__YZP_xxxxxxxx__` 全由下划线与十六进制组成，能通过
    `services.SERVICE_NAME_RE`，被当成一个真服务混进服务列表。

    因此这里做**容忍任意空白插入**的匹配：把 `sent` 当作 `head` 的子序列去走，
    允许 `head` 在字符之间多出空白。折行只会*插入*空白、不会删改字符，所以这是
    精确匹配，且与断点位置无关。`head` 开头通常是提示符（`root@XiaoQiang:~# `）
    这类非空白内容，所以先定位回显起点再走匹配。

    找不到（对端不回显）时原样返回 —— 此时 `head` 本就是纯输出。
    """
    if not sent:
        return head
    pos = head.find(sent)
    if pos >= 0:                                  # 常见情形：回显未被折行
        return _drop_leading_blank_lines(head, pos + len(sent))
    start = sent[0]
    # 从后往前找回显起点：`sent` 的首字符（如 `for` 的 `f`）在同一条回显里可能
    # 重复出现（命令自身含同名字符），从前往后找会匹配到靠前的那次并在半途停下，
    # 真机上表现为输出里残留命令的尾部碎片（如 `fc71__`）。回显在 head 里只有
    # 一份，取最后一次成功匹配才正确。
    for begin in range(len(head) - 1, -1, -1):
        if head[begin] != start:
            continue
        end = _match_lenient(head, sent, begin)
        if end >= 0:
            return _drop_leading_blank_lines(head, end)
    return head                                    # 不是回显（或对端不回显）
LOGIN_RE = re.compile(r"login:", re.I)
PASSWORD_RE = re.compile(r"password:", re.I)
BAD_LOGIN_RE = re.compile(
    r"login incorrect|incorrect password|authentication fail", re.I)
RECV_SIZE = 4096
_KEEP_WS = ("\n", "\t")   # 保留的空白（行 + ps 对齐）；其余控制字符丢弃


class TelnetError(Exception):
    """telnet 会话基础异常（连接/认证/超时之外的其它会话错误）。"""


class TelnetConnectError(TelnetError):
    """连接阶段失败：拒绝 / 不可达 / DNS 失败 / connect 超时。"""


class TelnetLoginError(TelnetError):
    """认证失败（口令错）。与 TelnetTimeoutError 严格区分，调用方不重试。"""


class TelnetTimeoutError(TelnetError):
    """读超时：连上了但对方在时限内没给出期望内容（路由器忙 / 未响应）。"""


def _create_socket():
    """默认 socket 工厂（测试也可整体替换本模块此函数）。"""
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def _strip_iac(data: bytes) -> bytes:
    """剥离 telnet 协议转义序列（IAC=0xFF 起头）。

    `IAC <cmd>` 与 `IAC SB ... IAC SE` 整体丢弃（不回应答）；`IAC IAC`（字面
    0xFF）也丢弃——非可打印，且避免解码结果随分包边界漂移。序列被边界截断时按
    「已丢弃前缀」处理：本函数对整块原始缓冲幂等，调用方每次整体重解。
    """
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b != 0xFF:
            out.append(b)
            i += 1
            continue
        i += 1
        if i >= n:                       # 序列被截断
            break
        cmd = data[i]
        i += 1
        if cmd == 0xFA:                  # SB ... IAC SE
            while i < n:
                if data[i] == 0xFF and i + 1 < n and data[i + 1] == 0xF0:
                    i += 2
                    break
                i += 1
    return bytes(out)


def decode_telnet(data: bytes) -> str:
    """字节流 → 纯文本：剥离 IAC 序列 → CRLF 归一为 \\n → 去控制字符（utf-8/replace）。"""
    text = _strip_iac(data).decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in _KEEP_WS or ch.isprintable())


class TelnetSession:
    """一次性 telnet 会话；`with TelnetSession(...) as s` 打开，一次连接内可跑多条命令。"""

    def __init__(self, host, port=23, user="root", password="",
                 connect_timeout=8.0, read_timeout=12.0, *, socket_factory=None):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._socket_factory = socket_factory
        self._sock = None
        self._closed = False
        self._raw = bytearray()   # 未消费的原始字节
        self._cut = 0             # 已消费字符数（相对 _text() 的下标）
        self._exchange_hook = None   # 录制接缝；None 时零行为变化

    @property
    def connected(self) -> bool:
        """会话是否仍可用（已连接且未被 close/断链）。"""
        return self._sock is not None and not self._closed

    def set_exchange_hook(self, hook) -> None:
        """安装登录握手的收发上报接缝（默认 ``None``，零行为变化）。

        ``hook`` 收到 ``{"kind": str, "send": str, "recv": str}``；抛出的任何异常
        都会被 :meth:`_emit` 吞掉 —— 录制是旁路能力，录制出问题绝不能弄挂登录。
        只上报登录握手，不上报 :meth:`run` 的命令收发（命令由录制侧包装器记录）。
        """
        self._exchange_hook = hook

    def _emit(self, event: dict) -> None:
        hook = self._exchange_hook
        if hook is None:
            return
        try:
            hook(event)
        except Exception:
            _log.debug("录制接缝 hook 抛异常，已忽略", exc_info=True)

    def _text(self) -> str:
        """把已收到的原始字节重解为纯文本（整体重解，规避分包边界问题）。"""
        return decode_telnet(bytes(self._raw))

    def open(self) -> None:
        """连接 → 等 login → 发 user → 等 Password → 发 password → 等提示符。
        已连接时为空操作；失败时自动 close()，不留半开 socket。
        """
        if self.connected:
            return
        factory = self._socket_factory or _create_socket
        sock = factory()
        self._raw.clear()
        self._cut = 0
        self._closed = False
        try:
            sock.settimeout(self.connect_timeout)
            sock.connect((self.host, self.port))
        except OSError as exc:
            _safe_close(sock)
            raise TelnetConnectError(
                f"无法连接 {self.host}:{self.port}：{exc}") from exc
        self._sock = sock
        try:
            self._login()
        except TelnetError:
            self.close()
            raise

    def close(self) -> None:
        """关闭连接（幂等）。置 SO_LINGER 避免 TIME_WAIT 堆积。"""
        sock, self._sock = self._sock, None
        self._closed = True
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            struct.pack("ii", 1, 0))
        except OSError:
            pass
        _safe_close(sock)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def run(self, command, *, timeout=None) -> str:
        """执行一条命令并返回其输出（剔除结束标记行与 tty 回显行）。
        读不到结束标记时按 timeout（缺省 read_timeout）截止，抛 TelnetTimeoutError。
        """
        if not self.connected:
            raise TelnetError("会话未打开，请先 open()")
        marker = MARKER_PREFIX + uuid.uuid4().hex[:8] + MARKER_SUFFIX
        limit = self.read_timeout if timeout is None else float(timeout)
        # 标记前强制补一条空 `echo`：命令输出若不以换行结尾（如 `tr '\n' ' '`
        # 把结尾换行也替换掉了），`echo MARKER` 的输出会粘在输出行末，标记不再
        # 独占一行，而 `MARKER_LINE_RE` 是行锚定的 —— 那样只能卡满 read_timeout
        # 再抛异常（真机实测 `busybox --list | tr '\n' ' '` 稳定复现）。多一条
        # 空 `echo` 保证标记永远从行首开始，且该空行随后被 strip("\r\n") 裁掉。
        sent = f"{command}; echo; echo {marker}"
        self._send(sent)
        m = self._await(MARKER_LINE_RE, limit, f"执行 {command!r}")
        head = self._text()[self._cut:m.start()]
        self._cut = m.end()
        head = _strip_echo(head, sent)
        # 首尾都只裁 CR/LF：回显尾随的换行与命令输出前的空行都不属于输出内容，
        # 而所有调用方（parse_uci / parse_ifconfig / parse_arp …）都是逐行解析。
        # 不用 strip() 是因为 `ps` / `df` 输出首行的缩进属于内容，不能动。
        return head.strip("\r\n")

    def run_batch(self, commands, *, timeout=None) -> list:
        """一次连接内顺序执行多条命令，返回与输入等长的 list。
        单条失败（超时/断链/未打开）只让对应元素为 ""，不抛异常中断整批。
        """
        results = []
        for command in (commands or []):
            if not self.connected:
                results.append("")
                continue
            try:
                results.append(self.run(command, timeout=timeout))
            except TelnetError:
                results.append("")
        return results

    def _login(self):
        # 登录三阶段里「提示符之前」的文本（横幅 / 用户名回显）一律丢弃；
        # 每阶段消费掉的文本片段经 _emit 上报给录制接缝（消费起点即上一段末尾）。
        start = self._cut
        self._cut = self._await(
            LOGIN_RE, self.read_timeout, "等待 login 提示").end()
        self._emit({"kind": "login_prompt", "send": "",
                    "recv": self._text()[start:self._cut]})
        self._send(self.user)
        self._emit({"kind": "username_sent", "send": self.user, "recv": ""})
        start = self._cut
        self._cut = self._await(
            PASSWORD_RE, self.read_timeout, "等待 Password 提示").end()
        self._emit({"kind": "password_prompt", "send": "",
                    "recv": self._text()[start:self._cut]})
        self._send(self.password)
        self._emit({"kind": "password_sent", "send": self.password, "recv": ""})
        start = self._cut
        try:
            self._cut = self._await(
                PROMPT_RE, self.read_timeout, "等待 shell 提示符",
                fail_re=BAD_LOGIN_RE).end()
        except TelnetLoginError:
            self._emit({"kind": "login_error", "send": "",
                        "recv": self._text()[start:]})
            raise
        self._emit({"kind": "login_ok", "send": "",
                    "recv": self._text()[start:self._cut]})

    def _await(self, pattern, timeout, stage, fail_re=None):
        """读到匹配为止并返回 match 对象（不移动 _cut，由调用方决定消费到哪）。"""
        deadline = time.monotonic() + timeout
        while True:
            text = self._text()
            m = pattern.search(text, self._cut)
            if m is not None:
                return m
            if fail_re is not None and fail_re.search(text, self._cut):
                raise TelnetLoginError("认证失败：路由器拒绝了该口令")
            left = deadline - time.monotonic()
            if left <= 0:
                raise TelnetTimeoutError(f"{stage}超时（{timeout:.1f}s 无响应）")
            self._recv(left)

    def _send(self, line: str) -> None:
        try:
            self._sock.sendall((line + "\n").encode("utf-8"))
        except OSError as exc:
            raise TelnetError(f"发送失败：{exc}") from exc

    def _recv(self, timeout: float) -> None:
        self._sock.settimeout(timeout)
        try:
            chunk = self._sock.recv(RECV_SIZE)
        except (socket.timeout, TimeoutError) as exc:
            raise TelnetTimeoutError(f"读取超时（{timeout:.1f}s）") from exc
        except OSError as exc:
            self._closed = True
            raise TelnetError(f"连接中断：{exc}") from exc
        if not chunk:
            self._closed = True
            raise TelnetError("连接已被对端关闭")
        self._raw.extend(chunk)


def _safe_close(sock) -> None:
    try:
        sock.close()
    except OSError:
        pass
