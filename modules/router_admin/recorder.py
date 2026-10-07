"""router_admin 录制侧：把真实会话包一层记录 (send, recv) 并落盘（层 D）。

录制开关由环境变量控制（见 :data:`ENV_RECORD_PATH`）——默认关闭，只有需要从
真机抓一份真实会话序列时手工打开；关闭时 :func:`wrap_if_recording` 原样返回
真实会话，零开销。

两条硬约束：

- **脱敏只发生在落盘副本上**：:class:`RecordingSession` 透传给调用方的仍是
  未脱敏的真实输出（备份校验/配置比对依赖真值），只有写进录制文件的那一份被
  :func:`~modules.router_admin.replay.redact` 抹成 :data:`~modules.router_admin.replay.REDACTED`；
- **录制失败绝不许弄挂真实任务**：落盘异常（磁盘满、路径不可写）一律吞掉。
  录制是旁路的诊断能力，不能让它把真机任务带崩 —— 这也是「开启录制后线上行为
  与不开完全一致」的前提。

会话接口（open/close/connected/run/run_batch）严格对齐
:class:`~modules.router_admin.telnet.TelnetSession`，因此可以透明地替换它。

纯 stdlib、无 Qt，便于离线单测。
"""
import os
from datetime import datetime

from .replay import dump_recording, redact

#: 设置为录制文件路径即开启录制；未设置/为空 → 完全不录制。
ENV_RECORD_PATH = "YZPLAN_RECORD_TELNET"

#: 写入录制文件的设备名（仅元信息）；未设置时用 ``wrap_if_recording`` 的
#: ``default_device``。
ENV_RECORD_DEVICE = "YZPLAN_RECORD_DEVICE"


class RecordingSession:
    """装饰器：接口对齐 TelnetSession，把每条命令的 (send, recv) 脱敏后记下来。

    内层会话按原样调用（透传 open/close/connected），记录完全旁路：录制坏了也
    只是少一份文件，真实任务照跑照返回。

    **落盘是按任务整体覆盖，不是追加**：`RouterTask.run()` 的 ``finally`` 会调
    ``_close()`` → ``close()`` → :meth:`flush`，而 :func:`dump_recording` 用 ``"w"``
    模式重写整个文件。因此连着录两个任务时，文件里只剩**最后一个**任务的序列
    —— 要一次录多个任务，得给每个任务单独的路径。
    """

    def __init__(self, inner, path, *, device="unknown", firmware="",
                 secrets=(), captured_at=None):
        self._inner = inner
        self._path = path
        self._device = device
        self._firmware = firmware
        self._secrets = tuple(secrets or ())
        self._captured_at = captured_at or datetime.now().isoformat(timespec="seconds")
        self._steps = []
        self._flushed = False

    def __getattr__(self, name):
        """未显式实现的属性透传给内层会话。

        TelnetSession 后续加接口（如 sendall）时，这里不用跟着改。用
        ``object.__getattribute__`` 取 ``_inner``：``__init__`` 之前若属性缺失，
        直接 ``self._inner`` 会再次触发 ``__getattr__`` 无限递归。
        """
        return getattr(object.__getattribute__(self, "_inner"), name)

    @property
    def connected(self) -> bool:
        """内层会话是否可用（未 open / 已 close 都是 False）。"""
        return self._inner.connected

    def open(self) -> None:
        """先装握手录制接缝再 open 内层 —— 登录握手发生在 open() 内部。

        ``set_exchange_hook`` 用 ``getattr`` 探测：任何接口对齐 TelnetSession 的
        替身（测试假内层等）没有这个可选能力时，退化为只录命令步。
        """
        setter = getattr(self._inner, "set_exchange_hook", None)
        if setter is not None:
            setter(self._record_exchange)
        self._inner.open()

    def _record_exchange(self, event: dict) -> None:
        """接缝回调：把一次握手收发脱敏后追加为一步。

        异常由内层的 ``_emit`` 吞掉，但这里仍然只做纯内存 append —— 录制失败的
        可能性被压到最小，登录流程不因录制而改变。
        """
        self._steps.append({
            "kind": event.get("kind", "command"),
            "send": redact(event.get("send", ""), self._secrets),
            "recv": redact(event.get("recv", ""), self._secrets),
        })
        self._flushed = False

    def close(self) -> None:
        """先落盘再关内层：close 是正常路径的收尾，录制文件不能因为它丢了。

        这条路径由每个后台任务的 ``finally`` 触发（即**每个任务结束**就落盘，
        不必等程序退出），但落的是**整体覆盖**：同一路径连录多个任务只剩最后一个。
        """
        self.flush()
        self._inner.close()

    def run(self, command, *, timeout=None) -> str:
        """执行一条命令；返回**未脱敏**的真实输出，落盘的那份才脱敏。"""
        output = self._inner.run(command, timeout=timeout)
        self._steps.append({"kind": "command",
                            "send": redact(command, self._secrets),
                            "recv": redact(output, self._secrets)})
        self._flushed = False
        return output

    def run_batch(self, commands, *, timeout=None) -> list:
        """顺序执行多条命令，逐条记录；返回与输入等长的**未脱敏**真实输出 list。"""
        commands = list(commands or [])
        outputs = self._inner.run_batch(commands, timeout=timeout)
        for command, output in zip(commands, outputs):
            self._steps.append({"kind": "command",
                                "send": redact(command, self._secrets),
                                "recv": redact(output, self._secrets)})
        self._flushed = False
        return outputs

    def flush(self) -> None:
        """落盘已记录的步骤。

        无新步骤时直接返回（幂等）。落盘失败只吞不抛 —— 录制是旁路能力，磁盘满
        或路径不可写都不该让真实任务失败；此时不置位，下次 flush 会重试。
        """
        if self._flushed:
            return
        try:
            dump_recording(self._path, device=self._device, firmware=self._firmware,
                           captured_at=self._captured_at, steps=self._steps)
        except (OSError, ValueError):
            return
        self._flushed = True


def wrap_if_recording(session, *, secrets=(), environ=None,
                      default_device="unknown"):
    """按环境变量开关决定是否把会话包一层录制。

    :data:`ENV_RECORD_PATH` 未设置或为空 → 原样返回 ``session``（默认路径，
    录制完全关闭）；否则返回 :class:`RecordingSession`，设备名取
    :data:`ENV_RECORD_DEVICE`，未设置则用 ``default_device``。

    路径原样使用（不 strip）：用户指定的落点就是他要的位置，静默改写反而会写到
    他没要求的地方。取值非法导致的落盘失败由 :meth:`RecordingSession.flush`
    吞掉，不会外泄。
    """
    env = os.environ if environ is None else environ
    path = env.get(ENV_RECORD_PATH, "")
    if not path:
        return session
    return RecordingSession(
        session, path, device=env.get(ENV_RECORD_DEVICE) or default_device,
        secrets=secrets)
