"""router_admin 录制/回放：真机录制的格式定义与按序回放会话（层 D）。

背景：2026-09-29 router 出现过一次生产备份损坏事故，根因是测试用手写理想化
替身（对任何命令都回固定字符串），替身不会暴露真实命令序列与真实输出形状。
本模块把替身换成「真机录制、按序回放」：

- 录制文件是一个 JSON，结构为
  ``{"device": str, "firmware": str, "captured_at": str,
    "steps": [{"send": str, "recv": str}, ...]}``；
- :class:`ReplaySession` 模拟 :class:`~modules.router_admin.telnet.TelnetSession`
  的会话接口（open/close/connected/run/run_batch），逐条比对命令、返回录制输出。

刻意保持严格的失败语义：**命令与录制不匹配、或序列已用尽，一律抛
AssertionError 且不前进**。宽松化（失配时返回空串继续跑）会把「代码改了命令
序列」变成静默通过，恰好重演那起事故。录制脱敏（口令 → :data:`REDACTED`）与
录制开关在后续任务追加。

纯 stdlib、无 Qt，便于离线单测。
"""
import json
import re

#: 录制格式版本；结构不兼容变更时递增并让旧文件显式失败。
RECORD_FORMAT_VERSION = 1

#: 录制时对敏感值（口令等）的占位符；回放时当作任意内容的通配。
REDACTED = "***"

_META_KEYS = ("device", "firmware", "captured_at")


def _invalid(reason):
    return ValueError(f"录制文件非法：{reason}")


def load_recording(path):
    """读取并校验一个录制文件，返回规范化后的录制字典。

    缺失的 ``device``/``firmware``/``captured_at`` 回填 ``""``；``steps`` 必须是
    list，每步是含 str 型 ``send``/``recv`` 的 dict。任何结构偏差抛 ValueError
    ——录制文件会被切到 CI 上，必须在解析层就挡下，不能带着半个会话跑到断言里。
    """
    with open(path, encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise _invalid(f"不是合法 JSON（{exc}）") from exc
    if not isinstance(raw, dict):
        raise _invalid(f"顶层应为对象，实际为 {type(raw).__name__}")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise _invalid(f"steps 应为列表，实际为 {type(steps).__name__}")
    normalized = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise _invalid(f"第 {i} 步应为对象，实际为 {type(step).__name__}")
        for key in ("send", "recv"):
            if key not in step:
                raise _invalid(f"第 {i} 步缺少 {key}")
            if not isinstance(step[key], str):
                raise _invalid(
                    f"第 {i} 步的 {key} 应为字符串，实际为 {type(step[key]).__name__}")
        normalized.append({"send": step["send"], "recv": step["recv"]})
    rec = {key: raw.get(key, "") for key in _META_KEYS}
    rec["steps"] = normalized
    return rec


def _matches(expected, command):
    """录制命令是否匹配本次调用。

    录制里敏感值已被替换为 :data:`REDACTED`（如 ``uci set ...password='***'``），
    回放传入的是真实口令，所以按 ``***`` 切段、各段 re.escape 后用 ``.*?``
    连接再 fullmatch。无 ``***`` 时就是精确匹配。
    """
    parts = expected.split(REDACTED)
    pattern = ".*?".join(re.escape(part) for part in parts)
    return re.fullmatch(pattern, command, re.S) is not None


class ReplaySession:
    """按序回放一份录制，接口对齐 TelnetSession。

    一次连接（open → 多次 run → close）对应录制里 steps 的一段连续切片；每条
    run 消费一步。open() 会把进度重置到 0，因此可重复回放同一条序列。
    """

    def __init__(self, steps, *, name="recording"):
        self.name = name
        self._steps = [{"send": s["send"], "recv": s["recv"]} for s in steps]
        self._opened = False
        self._closed = False
        self._index = 0

    @classmethod
    def from_file(cls, path, *, name=None):
        """从录制文件构造会话（校验交给 :func:`load_recording`）。"""
        rec = load_recording(path)
        return cls(rec["steps"], name=name or rec.get("device") or "recording")

    @property
    def connected(self) -> bool:
        """已 open 且未 close 才算可用（未 open 时也为 False）。"""
        return self._opened and not self._closed

    @property
    def consumed(self) -> int:
        """已消费的步数。"""
        return self._index

    @property
    def remaining(self) -> int:
        """剩余步数。"""
        return len(self._steps) - self._index

    def open(self) -> None:
        """开始（重新）回放：进度归零。"""
        self._opened = True
        self._closed = False
        self._index = 0

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
        if _matches(step["send"], command):
            self._index += 1
            return step["recv"]
        raise AssertionError(
            f"命令与录制不匹配（第 {self._index + 1} 步）："
            f"录制={step['send']!r} 实际={command!r}")

    def run_batch(self, commands, *, timeout=None) -> list:
        """按序回放多条命令，返回与输入等长的 list（任一条失败即抛出）。"""
        return [self.run(c, timeout=timeout) for c in (commands or [])]