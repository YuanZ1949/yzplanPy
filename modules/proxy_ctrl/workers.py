"""proxy_ctrl.workers：耗时代理操作的后台线程封装（绝不进 UI 线程）。

一次局域网扫描可达数分钟、一次测速 5 轮各 30s、一次 `git config` 也要起进程，
全部放主线程会让窗口假死。本文件分两段：

- **线程层**：`describe_error` / `JobContext` / `ProxyTask` / `TaskGroup`
- **任务层**：`xxx_worker(ctx, ...)`，签名固定 `worker(ctx) -> object`

本文件**不拼任何网络目标字符串**：地址一律由纯逻辑层（scanner / speedtest /
targets）构造，UI 只负责传参与渲染。

线程收口三重保险（缺一条 pytest 就会挂在悬挂线程上）：`settled` 排队执行
`_on_settled` → `quit()`+`wait()`+`_retire()`；页面 `destroyed` →
`shutdown()`；QThread 挂在 TaskGroup parent 上。`_retire` 见其 docstring：
缺它那一步会 abort（与 right_menu 同一模式）。

**错误必须留痕**：catch-all 除 emit 给 UI 外还要 `logger.exception` 落 traceback
（→ yzplan.log + GUI 错误计数 + stderr.log），分类失败落 `logger.warning`
（见 tests/test_module_logging.py）。
"""
import logging
import threading
from datetime import datetime

from core.qt_bootstrap import import_qt

from . import scanner, speedtest, store, targets

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger(__name__)

#: shutdown 时 join 的超时（ms），超了就 terminate 兜底
_JOIN_MS = 4000

#: 扫描历史的时间戳格式（与 backup / router_admin 一致的可读格式）
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _retire(task):
    """销毁已 join 完的 QThread——**必须当场送达**，不能只 `deleteLater()`。

    `deleteLater()` 只是往队列投一条 DeferredDelete。若此后 TaskGroup 先被 GC 掉（测试出
    作用域或页面重建），`~QObject` 连带释放子 QThread，那条事件仍在队列里 → 下个
    `processEvents()` 写入已释放内存 → abort（崩溃点落在**后一个**测试，与出事者毫无栈
    关系）。故 `quit()+wait()` 后立刻 `sendPostedEvents` 投递干净——参照
    `right_menu/workers.py::_retire`（其 docstring 点名本模块缺此步）。
    """
    task.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(task, QtCore.QEvent.DeferredDelete)


def describe_error(exc):
    """任意异常 → (分类, 可读文案)。代理地址可以出现，**任何凭据都不写进文案**。"""
    if isinstance(exc, scanner.ScanRejected):
        return "reject", f"{exc}\n请调整网段或端口后重试。"
    if isinstance(exc, FileNotFoundError):
        return "missing", f"找不到可执行文件：{exc.filename or exc}\n请确认已安装。"
    if isinstance(exc, OSError):
        return "io", f"系统调用失败：{exc}"
    if isinstance(exc, ValueError):
        return "invalid", f"参数不合法：{exc}"
    return "unknown", f"未预期的错误：{exc}"


class JobContext:
    """传给任务层的句柄：取消标志 + 进度回调。

    单独抽出来是为了让任务层不依赖 Qt —— `scanner` 只认 `threading.Event`，
    UI 侧也只需一个 `progress` 回调，两边都不必知道 QThread 的存在。
    """

    def __init__(self, on_progress=None):
        self.cancel = threading.Event()
        self._on_progress = on_progress

    def request_cancel(self):
        self.cancel.set()

    @property
    def cancelled(self):
        return self.cancel.is_set()

    def progress(self, done, total=1.0):
        """转发进度。UI 回调抛异常绝不能中断扫描。"""
        if self._on_progress is None:
            return
        try:
            self._on_progress(done, total)
        except Exception:
            pass


class ProxyTask(QtCore.QThread):
    """后台跑 `worker(JobContext) -> object`。

    成功发 `succeeded(result)`、失败发 `failed(分类, 文案)`，最后都发
    `settled()`（供 UI 解除 busy + 收口线程）。被 `stop()` 后不再发结果信号。
    """

    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str, str)
    settled = QtCore.Signal()

    def __init__(self, worker, *, label="", on_progress=None, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._label = label
        self._stopped = False
        self.ctx = JobContext(on_progress)

    @property
    def label(self):
        return self._label

    def stop(self):
        """请求中断：置停止位并置位 cancel 事件（scanner / _run_pool 会读到它）。"""
        self._stopped = True
        self.ctx.request_cancel()

    def run(self):
        try:
            result = self._worker(self.ctx)
            if not self._stopped:
                self.succeeded.emit(result)
        except Exception as exc:                        # noqa: BLE001 - 兜底成 UI 文案
            if not self._stopped:
                kind, text = describe_error(exc)
                if kind == "unknown":
                    # 未分类异常必须留 traceback，否则事后无法回溯
                    logger.exception("后台任务未预期异常（label=%s）", self._label)
                else:
                    logger.warning("后台任务失败（%s，label=%s）：%s",
                                   kind, self._label, exc)
                self.failed.emit(kind, text)
        finally:
            self.settled.emit()


class TaskGroup(QtCore.QObject):
    """串行化一批 ProxyTask：忙时拒绝新任务，结束即收口，关闭时全部中断。"""

    idle = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task = None
        self.on_error = None        # (分类, 文案) 的缺省处理
        self.on_success = None      # 无参回调：任一任务成功时触发

    @property
    def busy(self):
        return self._task is not None

    def start(self, worker, *, on_ok=None, on_err=None, on_progress=None, label=""):
        """起一个后台任务。忙则返回 False（调用方需自行给出提示）。"""
        if self.busy or worker is None:
            return False
        task = ProxyTask(worker, label=label, on_progress=on_progress, parent=self)
        task.succeeded.connect(self._wrap_ok(on_ok))
        handler = on_err if on_err is not None else self.on_error
        if handler is not None:            # 两端都没有处理器时不连（connect(None) 会抛）
            task.failed.connect(handler)
        task.settled.connect(self._on_settled)
        self._task = task
        task.start()
        return True

    def cancel(self):
        """请求中断当前任务（不阻塞）。"""
        task = self._task
        if task is not None:
            task.stop()

    def _wrap_ok(self, on_ok):
        def wrapper(result):          # 业务回调前先广播成功
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
            _retire(task)
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
        _retire(task)


# ── 任务层：读 / 写 / 扫描 / 测速 ────────────────────────────────────

def read_targets_worker(ctx):
    """读全部代理目标 → [{id, name, note, value, available}]。

    某个目标读失败只降级为「读不到」，绝不让整轮失败（原版是逐项提示）。
    """
    rows = []
    for target in targets.all_targets():
        value, err = None, ""
        try:
            value = target.read()
        except Exception as exc:                        # noqa: BLE001 - 单项降级
            err = str(exc)
        available = True
        if isinstance(target, targets.GitTarget):
            available = target.available()
        elif isinstance(target, targets.DockerTarget):
            available = bool(target.existing())
        rows.append({"id": target.id, "name": target.name, "note": target.note,
                     "value": value or "", "available": available, "error": err})
    return {"rows": rows}


def apply_target_worker(ctx, target_id, url, action):
    """对单个目标执行 set / unset。action ∈ {"set", "unset"}。

    动作名与目标 id 都由 UI 从 `all_targets()` 的固定集合里取，层上还有
    ProxyTarget 自身的实现，**不存在命令注入面**（git 走 argv 列表，
    环境变量走 winreg 键名白名单）。
    """
    for target in targets.all_targets():
        if target.id == target_id:
            return {"id": target.id, "name": target.name,
                    "result": target.set(url) if action == "set" else target.unset()}
    raise ValueError(f"未知的代理目标：{target_id}")


def apply_all_worker(ctx, url, action):
    """对全部目标批量执行 set / unset，返回逐项结果。"""
    results = []
    for target in targets.all_targets():
        try:
            outcome = target.set(url) if action == "set" else target.unset()
        except Exception as exc:                        # noqa: BLE001 - 单项降级
            outcome = targets.TargetResult(False, "操作异常", str(exc))
        results.append({"id": target.id, "name": target.name, "result": outcome})
    return {"results": results, "action": action, "url": url}


def scan_worker(ctx, *, subnet, port_spec, timeout, max_workers,
                verify_max_workers, include_self):
    """扫描局域网 → {results, warnings, ports, cancelled, timestamp}。

    取消走 `ctx.cancel`：`scanner` 的 `_run_pool` 每批都检查该事件，因此
    中断后最多再跑完一个批次（≤ max_workers×4 个任务）就收工。
    """
    ports, warnings = scanner.parse_port_range(
        port_spec or " ".join(str(p) for p in scanner.DEFAULT_PORTS))
    found = scanner.scan(
        subnet, port_spec, timeout=timeout, max_workers=max_workers,
        verify_max_workers=verify_max_workers, cancel=ctx.cancel,
        exclude_self=not include_self, on_progress=ctx.progress)
    return {"results": found, "warnings": warnings, "ports": ports,
            "cancelled": ctx.cancelled, "subnet": subnet,
            "timestamp": datetime.now().strftime(_TS_FMT)}


def save_scan_worker(ctx, subnet, results, timestamp):
    """把一次扫描落盘。失败只返回 False，UI 给提示但不丢表格。"""
    return {"saved": store.add_scan(subnet, results, timestamp=timestamp)}


def speed_worker(ctx, url, rounds):
    """测速。空 url 由 speedtest 自己判为「无需代理」，不额外拦。"""
    return speedtest.test_proxy_speed(url, rounds=rounds)



def check_worker(ctx, url):
    """后台可用性快检。返回 `speedtest.check_proxy_availability` 的 (ok, detail)。

    **阻塞调用，必须进后台线程**（快检也要 2~5 秒）。真正的实现与目标地址
    都在纯逻辑层 `speedtest`，本函数只做线程封装。
    """
    return speedtest.check_proxy_availability(url)
