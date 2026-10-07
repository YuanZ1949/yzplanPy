"""router_admin.workers：后台 telnet 任务线程（绝不进 UI 线程）。

一次 telnet 登录 + 一轮采集约 1~3 秒，放主线程会让窗口假死，故本文件分两段：
**线程层**（`describe_error` / `RouterTask` / `TaskGroup`）与**任务层**（各 Tab 的
`xxx_worker(...)`，签名固定 `worker(session) -> dict`）。任务层放这里而不是 tab
文件里，是为了让 tab 只保留「渲染 + 确认 + 点线」，把每个文件压在 250 行以内。
命令一律由纯逻辑层构造，本文件**不拼任何命令字符串**。线程收口三重保险（缺一条
pytest 就会挂在悬挂线程上）：`settled` 排队执行 `_on_settled` → `quit()`+`wait()`
+`deleteLater()`；页面 `destroyed` → `shutdown()`；QThread 挂在 TaskGroup parent 上。

**错误必须留痕**：catch-all 除 emit 给 UI 外还要 `logger.exception` 落 traceback
（→ yzplan.log + GUI 错误计数 + stderr.log），分类失败落 `logger.warning`——只
弹 UI 的静默错误事后无法回溯（「未预期的错误」排查的直接教训，见
tests/test_module_logging.py）。
"""
import logging

from core.qt_bootstrap import import_qt

from . import backup, config_editor, services
from .connection import ConnectionParams
from .recorder import wrap_if_recording
from .telnet import (MARKER_PREFIX, TelnetConnectError, TelnetError,
                     TelnetLoginError, TelnetSession, TelnetTimeoutError)

_, QtCore, QtGui, QtWidgets = import_qt()
_JOIN_MS = 4000     # shutdown 时 join 的超时（ms），超了就 terminate 兜底

logger = logging.getLogger(__name__)

def describe_error(exc):
    """TelnetError（或任意异常）→ (分类, 可读文案)。绝不把口令写进文案。"""
    if isinstance(exc, TelnetLoginError):
        return "login", f"{exc}\n请检查路由器的 root 口令是否正确。"
    if isinstance(exc, TelnetConnectError):
        return "connect", f"{exc}\n请确认地址/端口填写正确，且本机能访问该网段。"
    if isinstance(exc, TelnetTimeoutError):
        return "timeout", f"{exc}\n路由器可能在忙，或已经与本机失联，稍后可重试。"
    if isinstance(exc, TelnetError):
        return "session", f"telnet 会话中断：{exc}"
    return "unknown", f"未预期的错误：{exc}"


class RouterTask(QtCore.QThread):
    """后台跑 `callable(TelnetSession) -> object`。

    成功发 `succeeded(result)`、失败发 `failed(分类, 文案)`，最后都发 `settled()`
    （供 UI 解除 busy + 收口线程）。被 `stop()` 后不再发结果信号。
    """
    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str, str)
    settled = QtCore.Signal()

    def __init__(self, params, worker, *, label="", parent=None):
        super().__init__(parent)
        self._params, self._worker, self._label = params, worker, label
        self._session, self._stopped = None, False

    @property
    def label(self):
        return self._label

    def _close(self):
        """关掉当前会话（幂等，异常吞掉：关闭路径不该再抛）。"""
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def stop(self):
        """请求中断：置停止位并主动关 socket，让阻塞的 recv 立刻返回。"""
        self._stopped = True
        self._close()

    def _make_session(self):
        """构造本次任务的会话；开了录制开关（`recorder.ENV_RECORD_PATH`）则包一层记录。

        录制是**旁路的诊断能力**（层 D）：开关默认关闭，此时 `wrap_if_recording`
        原样返回真实会话，任务行为与没有这一层时逐字一致；打开时也只是在会话外面
        加一层装饰器，返回给 worker 的仍然是未脱敏的真值。
        """
        session = TelnetSession(
            self._params.host, self._params.port, self._params.user,
            self._params.password, self._params.connect_timeout,
            self._params.read_timeout)
        return wrap_if_recording(session, secrets=[self._params.password])

    def run(self):
        try:
            self._session = self._make_session()
            self._session.open()
            result = self._worker(self._session)
            if not self._stopped:
                self.succeeded.emit(result)
        except TelnetError as exc:
            if not self._stopped:
                kind, text = describe_error(exc)
                logger.warning("telnet 任务失败（%s，label=%s）：%s",
                               kind, self._label, exc)
                self.failed.emit(kind, text)
        except Exception as exc:                      # noqa: BLE001 - 兜底成 UI 文案
            if not self._stopped:
                # 全仓唯一「未预期错误」出口：必须留 traceback，否则事后无法回溯
                logger.exception("telnet 任务未预期异常（label=%s）", self._label)
                self.failed.emit("unknown", f"未预期的错误：{exc}")
        finally:
            self._close()
            self.settled.emit()


class TaskGroup(QtCore.QObject):
    """串行化一批 RouterTask：忙时拒绝新任务，结束即收口，关闭时全部中断。"""
    idle = QtCore.Signal()      # 任务结束（含失败）后触发，页面据此恢复按钮

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task = None
        self.params = None          # ConnectionParams | None：None = 未连接
        self.on_error = None        # (分类, 文案) 的缺省处理
        self.on_success = None      # 无参回调：任一任务成功时触发（推进在线状态）

    @property
    def busy(self):
        return self._task is not None

    def set_params(self, params):
        """设置/清除连接参数。None 表示断开（后续 start 一律拒绝）。"""
        self.params = ConnectionParams.from_settings(
            params) if isinstance(params, dict) else params

    def start(self, worker, *, on_ok=None, on_err=None, label=""):
        """起一个后台任务。忙或未连接返回 False（调用方需自行给出提示）。"""
        if self.busy or self.params is None or worker is None:
            return False
        task = RouterTask(self.params, worker, label=label, parent=self)
        task.succeeded.connect(self._wrap_ok(on_ok))
        handler = on_err if on_err is not None else self.on_error
        if handler is not None:            # 两端都没有处理器时不连（connect(None) 会抛）
            task.failed.connect(handler)
        task.settled.connect(self._on_settled)
        self._task = task
        task.start()
        return True

    def _wrap_ok(self, on_ok):
        def wrapper(result):          # 业务回调前先广播成功（推进 chip 到「在线」）
            if self.on_success is not None:
                self.on_success()
            if on_ok is not None:
                on_ok(result)
        return wrapper

    def _on_settled(self):
        """主线程收口：等线程真正结束再放掉引用，杜绝悬挂线程。"""
        task, self._task = self._task, None
        if task is not None:
            task.quit()
            task.wait()
            task.deleteLater()
        self.idle.emit()

    def shutdown(self):
        """页面关闭：中断 + join 全部在跑任务。可重复调用。"""
        task, self._task = self._task, None
        if task is None:
            return
        task.stop()
        task.quit()
        if not task.wait(_JOIN_MS):
            task.terminate()
            task.wait(_JOIN_MS)
        task.deleteLater()

# ── 配置编辑 Tab 的后台任务（命令由 config_editor / backup 构造）─────
def read_worker(section):
    """读一个白名单配置文件的当前内容。"""
    def worker(session):
        return {"section": section,
                "text": session.run(config_editor.build_read_command(section))}
    return worker


def backup_then_write(session, section, text):
    """备份 → 原子写回 → 回读校验。备份为空即中止（避免无备份改配置）。

    配置编辑 Tab 与宽带账号 Tab 共用这一条管道：两条写路径的**安全属性必须完全
    一致**（先备份、备份失败即中止、同目录临时文件 + mv、回读校验），所以收敛
    成一个函数，而不是各写一遍后各自漂移。
    """
    size = session.run(backup.build_remote_backup_command(section))
    old = session.run(backup.build_remote_read_command(section))
    if not (old or "").strip():
        return {"ok": False, "stage": "backup", "size": size,
                "error": "远端备份内容为空，已中止写入（避免无备份改配置）"}
    path = backup.save_backup(section, old)
    out = session.run(config_editor.build_write_command(section, text))
    return {"ok": "YZ_WRITE_OK" in (out or ""), "stage": "write", "backup": path,
            "size": size, "output": out,
            "verified": session.run(config_editor.build_verify_command(section))}


def save_worker(section, content):
    """备份 → 写回 → 回读校验，三步在一个会话里顺序执行。"""
    def worker(session):
        return backup_then_write(session, section, content)
    return worker


def restart_worker(service):
    """重启一个服务使配置生效（服务名来自静态白名单映射，非用户输入）。"""
    def worker(session):
        return {"service": service, "output": session.run(
            config_editor.build_service_restart_command(service))}
    return worker


def reboot_worker():
    """整机重启。重启会掐断会话，TelnetError 属预期而非失败。"""
    def worker(session):
        try:
            session.run(config_editor.build_reboot_command())
            note = "命令已送达，连接未中断。"
        except TelnetError as exc:
            note = f"命令已送达后连接断开（{exc}），属重启的预期表现。"
        return {"dispatched": True, "note": note}
    return worker


# ── 服务管理 Tab 的后台任务（命令由 services.py 构造）──────────────
#: 单条 telnet 命令的安全长度上限（字符）。
#:
#: **真机实测踩到的硬限制**：BusyBox tty 的规范输入行缓冲约 512 字节，命令超过就被
#: 截断。`build_autostart_command(70 个服务)` 拼出的 for 循环有 ~1050 字符，被截断后
#: shell 拿到的是残缺的 `for ... do`，永远等不到结束标记 → 12s 读超时。实测 450 字符
#: 可过、502 字符必挂。留出 `; echo __YZP_xxxxxxxx__`（22 字符）与安全余量后取 400。
#: 纯逻辑层不好改（它不感知传输层行长），故在任务层按**命令长度**切分。
CMD_CHAR_BUDGET = 400


def _chunks_by_len(names, budget=CMD_CHAR_BUDGET):
    """按「构造出的命令长度」而不是服务个数切分服务名。"""
    chunks, cur = [], []
    for name in names:
        trial = cur + [name]
        if cur and len(services.build_autostart_command(trial)) > budget:
            chunks.append(cur)
            cur = [name]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    return chunks


def collect_services(session):
    """服务列表 + 自启状态。返回 {rows, names}；自启查不到的行 autostart 为「—」。

    自启按长度切块后用 `run_batch` 跑：单块失败只留空串，不会让整轮采集抛异常。
    两处都要滤掉 `__YZP_*`：长命令的 tty 回显会折行，结束标记可能被切成独占一行
    抢先匹配，于是漏进下一次命令的输出里（真机实测 `list_command` 后偶发一条）。
    """
    names = [n for n in services.parse_service_list(
        session.run(services.list_command())) if not n.startswith(MARKER_PREFIX)]
    auto = {}
    if names:
        parts = session.run_batch(
            [services.build_autostart_command(c) for c in _chunks_by_len(names)])
        for part in parts:
            for key, value in services.parse_autostart(part).items():
                if not key.startswith(MARKER_PREFIX):
                    auto[key] = value
    rows = []
    for name in names:
        if name not in auto:
            text = "—"
        else:
            text = "开" if auto[name] else "关"
        rows.append({"name": name, "on": auto.get(name), "autostart": text})
    return {"rows": rows, "names": names}
