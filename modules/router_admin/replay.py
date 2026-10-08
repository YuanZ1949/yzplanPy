"""router_admin 录制/回放：真机录制的格式定义与按序回放会话（层 D）。

背景：2026-09-29 router 出现过一次生产备份损坏事故，根因是测试用手写理想化
替身（对任何命令都回固定字符串），替身不会暴露真实命令序列与真实输出形状。
本模块把替身换成「真机录制、按序回放」：

- 录制文件是一个 JSON，结构为
  ``{"version": int, "device": str, "firmware": str, "captured_at": str,
    "steps": [{"kind": str, "send": str, "recv": str}, ...]}``；
  ``kind`` 区分命令步（``"command"``，缺省）与登录握手段（见 :data:`_KINDS`）。
  v1 录制步里没有 ``kind``，一律按 ``"command"`` 兜底。
- :class:`ReplaySession`（实现在 :mod:`~modules.router_admin.replay_session`，
  本模块 re-export 保持既有 import 路径）模拟
  :class:`~modules.router_admin.telnet.TelnetSession` 的会话接口
  （open/close/connected/run/run_batch），逐条比对命令、返回录制输出。

刻意保持严格的失败语义：**命令与录制不匹配、或序列已用尽，一律抛
AssertionError 且不前进**。宽松化（失配时返回空串继续跑）会把「代码改了命令
序列」变成静默通过，恰好重演那起事故。

本模块是**录制格式的唯一拥有者**：读取（:func:`load_recording`）、写入
（:func:`dump_recording`）与脱敏（:func:`redact`）都在这里，录制侧的会话包装
（:class:`~modules.router_admin.recorder.RecordingSession`）在 recorder.py 单向
import 本模块，不反向依赖。

纯 stdlib、无 Qt，便于离线单测。
"""
import json
import os
import re

#: 录制格式版本；结构不兼容变更时递增并让旧文件显式失败。
#: v2：步新增 ``kind``（登录握手录制），v1 无 ``kind`` 仍可加载。
RECORD_FORMAT_VERSION = 2

#: 仍可加载的旧/当前格式版本。
SUPPORTED_RECORD_VERSIONS = frozenset({1, 2})

#: 步类型。未知 kind 视为录制文件损坏（宁可显式失败，也不静默跳过握手段）。
_KINDS = frozenset({
    "command",
    "login_prompt",
    "username_sent",
    "password_prompt",
    "password_sent",
    "login_ok",
    "login_error",
})

#: 登录握手段的 kind 集合。回放时这段被 open() 一次性消费；其中只收不发的
#: 回包步（login_prompt / password_prompt / login_ok）「消费但不比对」——
#: 回放侧没有真路由器，没有可比对的输入。命令步（command）的严格匹配语义不变。
_LOGIN_KINDS = frozenset({
    "login_prompt",
    "username_sent",
    "password_prompt",
    "password_sent",
    "login_ok",
    "login_error",
})

#: 录制时对敏感值（口令等）的占位符；回放时当作任意内容的通配。
REDACTED = "***"

_META_KEYS = ("device", "firmware", "captured_at")


def _invalid(reason):
    return ValueError(f"录制文件非法：{reason}")


def load_recording(path):
    """读取并校验一个录制文件，返回规范化后的录制字典。

    缺失的 ``device``/``firmware``/``captured_at`` 回填 ``""``；``steps`` 必须是
    list，每步是含 str 型 ``send``/``recv`` 的 dict，``kind`` 缺省为 ``"command"``
    且必须是 :data:`_KINDS` 之一。任何结构偏差抛 ValueError
    ——录制文件会被切到 CI 上，必须在解析层就挡下，不能带着半个会话跑到断言里。

    ``version`` 缺失时按 :data:`RECORD_FORMAT_VERSION` 兜底（v1 之前落盘的录制
    没有这个字段，仍要能回放）；存在时必须在 :data:`SUPPORTED_RECORD_VERSIONS`
    内，否则抛 ValueError ——这正是版本号存在的意义：结构不兼容时让旧/新文件
    **显式失败**，而不是按旧结构硬解出半个会话、在回放里报出误导性的
    「命令不匹配」。
    """
    with open(path, encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise _invalid(f"不是合法 JSON（{exc}）") from exc
    if not isinstance(raw, dict):
        raise _invalid(f"顶层应为对象，实际为 {type(raw).__name__}")
    version = raw.get("version", RECORD_FORMAT_VERSION)
    # bool 是 int 的子类：True == 1 会静默通过版本校验，故显式排除。
    if not isinstance(version, int) or isinstance(version, bool) \
            or version not in SUPPORTED_RECORD_VERSIONS:
        raise _invalid(f"录制格式版本为 {version!r}，不在支持范围 "
                       f"{sorted(SUPPORTED_RECORD_VERSIONS)}"
                       f"（当前为 {RECORD_FORMAT_VERSION}）（结构不兼容，无法回放）")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise _invalid(f"steps 应为列表，实际为 {type(steps).__name__}")
    normalized = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise _invalid(f"第 {i} 步应为对象，实际为 {type(step).__name__}")
        kind = step.get("kind", "command")
        if not isinstance(kind, str) or kind not in _KINDS:
            raise _invalid(f"第 {i} 步的 kind 未知：{kind!r}")
        for key in ("send", "recv"):
            if key not in step:
                raise _invalid(f"第 {i} 步缺少 {key}")
            if not isinstance(step[key], str):
                raise _invalid(
                    f"第 {i} 步的 {key} 应为字符串，实际为 {type(step[key]).__name__}")
        normalized.append({"kind": kind, "send": step["send"], "recv": step["recv"]})
    rec = {key: raw.get(key, "") for key in _META_KEYS}
    rec["version"] = RECORD_FORMAT_VERSION
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


def redact(value, secrets) -> str:
    """把 ``secrets`` 里每个非空串在 ``value`` 中的**所有**出现替换为 :data:`REDACTED`。

    跳过空串：``str.replace(v, "", REDACTED)`` 会在每两个字符之间插一遍
    :data:`REDACTED`（路由器允许不配口令，``secrets`` 里就会有空串），把整条
    命令搅成不可读，录制的意义也就没了。
    """
    for secret in secrets:
        if secret:
            value = value.replace(secret, REDACTED)
    return value


def dump_recording(path, *, device, firmware, captured_at, steps) -> None:
    """把一段录制写成 UTF-8 JSON（``ensure_ascii=False``、缩进 2，便于人工审阅 diff）。

    父目录不存在时先创建：录制路径来自环境变量，多半是随手指定的临时路径。

    每步恒写出 ``kind``（缺失按 ``"command"`` 兜底），与 :func:`load_recording`
    的校验保持一致：写出的文件必须能被自己读回来。

    失败**不**在这里吞 —— 由调用方（recorder 的 flush）决定，因为只有它知道
    「录制失败不该弄挂真实任务」这条约束的边界。
    """
    payload = {
        "version": RECORD_FORMAT_VERSION,
        "device": device,
        "firmware": firmware,
        "captured_at": captured_at,
        "steps": [{"kind": step.get("kind", "command"),
                   "send": step["send"], "recv": step["recv"]} for step in steps],
    }
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def __getattr__(name):
    """PEP 562 惰性 re-export：会话类实现在 :mod:`modules.router_admin.replay_session`。

    本模块在 v2 落地时涨到 284 行，超了 AGENTS.md 的 250 行上限，故把
    :class:`ReplaySession` 拆了出去；这里保留既有 import 路径
    （``from modules.router_admin.replay import ReplaySession``）。

    用惰性代理而非文件末尾的 ``from .replay_session import ReplaySession``：
    后者在调用方先 import ``replay_session`` 时会造成模块部分初始化的循环。
    """
    if name == "ReplaySession":
        from .replay_session import ReplaySession

        return ReplaySession
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
