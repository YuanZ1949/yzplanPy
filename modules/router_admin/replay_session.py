"""按序回放一份真机录制，会话接口对齐 :class:`~modules.router_admin.telnet.TelnetSession`。

从 :mod:`modules.router_admin.replay` 拆出（原文件 284 行，超 AGENTS.md 的
250 行上限）。职责边界：**录制格式**（读取/写入/脱敏/版本与 kind 常量）仍由
`replay.py` 独家拥有，本模块只消费它，单向 import，不反向依赖。

一次连接（open → 多次 run → close）对应录制里 steps 的一段连续切片；每条
run 消费一个**命令步**。v2 录制在命令步前还有一段登录握手段，由 :meth:`open`
一次性消费。

刻意保持严格的失败语义：**命令与录制不匹配、或序列已用尽，一律抛
AssertionError 且不前进**。宽松化（失配时返回空串继续跑）会把「代码改了命令
序列」变成静默通过——那正是 2026-09-29 备份损坏事故的形态。

纯 stdlib、无 Qt，便于离线单测。
"""
from .replay import _LOGIN_KINDS, _matches, load_recording
from .telnet import TelnetLoginError


class ReplaySession:
    """按序回放一份录制，接口对齐 TelnetSession。

    一次连接（open → 多次 run → close）对应录制里 steps 的一段连续切片；每条
    run 消费一个**命令步**。v2 录制在命令步前还有一段登录握手段（见
    :data:`~modules.router_admin.replay._LOGIN_KINDS`），由 :meth:`open` 一次性
    消费。

    ``open()`` 会把进度重置到 0，因此可重复回放同一条序列。``consumed`` /
    ``remaining`` **只统计命令步**（v1 录制无握手段，语义与升级前逐字一致）；
    握手消费量另由 :attr:`login_consumed` 报告。
    """

    def __init__(self, steps, *, name="recording"):
        self.name = name
        self._steps = [{"kind": s.get("kind", "command"),
                        "send": s["send"], "recv": s["recv"]} for s in steps]
        self._command_count = sum(1 for s in self._steps if s["kind"] == "command")
        self._opened = False
        self._closed = False
        self._index = 0
        self._cmd_consumed = 0
        self._login_consumed = 0

    @classmethod
    def from_file(cls, path, *, name=None):
        """从录制文件构造会话（校验交给 :func:`~modules.router_admin.replay.load_recording`）。"""
        rec = load_recording(path)
        return cls(rec["steps"], name=name or rec.get("device") or "recording")

    @property
    def connected(self) -> bool:
        """已 open 且未 close 才算可用（未 open 时也为 False）。"""
        return self._opened and not self._closed

    @property
    def consumed(self) -> int:
        """已消费的**命令步**数。"""
        return self._cmd_consumed

    @property
    def remaining(self) -> int:
        """剩余**命令步**数。"""
        return self._command_count - self._cmd_consumed

    @property
    def login_consumed(self) -> int:
        """已消费的登录握手段数（v1 录制恒为 0）。"""
        return self._login_consumed

    def open(self, username=None, password=None) -> None:
        """开始（重新）回放：进度归零，并消费前缀登录握手段。

        ``username`` / ``password`` 为 ``None`` 时不比对（调用方不关心）；给出时
        按 :func:`~modules.router_admin.replay._matches` 比对录制里的
        ``username_sent`` / ``password_sent``，失配抛 AssertionError。录制里
        ``password_sent`` 已被脱敏为 ``***``，因此任何真实口令都能匹配。遇到
        ``login_error`` 步——即真机录到的认证失败——抛
        :class:`TelnetLoginError`，与生产同一句文案。

        先检查再前进：任一步失配/失败都不消费该步。
        """
        self._opened = True
        self._closed = False
        self._index = 0
        self._cmd_consumed = 0
        self._login_consumed = 0
        while (self._index < len(self._steps)
               and self._steps[self._index]["kind"] in _LOGIN_KINDS):
            step = self._steps[self._index]
            kind = step["kind"]
            if kind == "username_sent" and username is not None \
                    and not _matches(step["send"], username):
                raise AssertionError(
                    f"登录握段用户名与录制不匹配（第 {self._index + 1} 步）："
                    f"录制={step['send']!r} 实际={username!r}")
            if kind == "password_sent" and password is not None \
                    and not _matches(step["send"], password):
                raise AssertionError(
                    f"登录握段口令与录制不匹配（第 {self._index + 1} 步）")
            self._index += 1
            self._login_consumed += 1
            if kind == "login_error":
                raise TelnetLoginError("认证失败：路由器拒绝了该口令")

    def close(self) -> None:
        """结束回放（幂等）。"""
        self._closed = True

    def run(self, command, *, timeout=None) -> str:
        """回放一条命令并返回录制输出（``timeout`` 为接口对齐，回放不等待）。"""
        if not self.connected:
            raise AssertionError(f"回放会话未 open()：{self.name}")
        if self._index >= len(self._steps):
            raise AssertionError(
                f"回放序列已用尽（{self.name} 共 {len(self._steps)} 步）："
                f"收到第 {self._index + 1} 条命令 {command!r}")
        step = self._steps[self._index]
        if step["kind"] != "command":
            raise AssertionError(
                f"第 {self._index + 1} 步是登录握段 {step['kind']!r}，"
                f"不能作为命令回放")
        if _matches(step["send"], command):
            self._index += 1
            self._cmd_consumed += 1
            return step["recv"]
        raise AssertionError(
            f"命令与录制不匹配（第 {self._index + 1} 步）："
            f"录制={step['send']!r} 实际={command!r}")

    def run_batch(self, commands, *, timeout=None) -> list:
        """按序回放多条命令，返回与输入等长的 list（任一条失败即抛出）。"""
        return [self.run(c, timeout=timeout) for c in (commands or [])]
