"""right_menu.workers：注册表读写的后台线程封装（绝不进 UI 线程）。

扫描两级菜单树要枚举整棵 HKCR/HKLM，隐藏/删除要等提权子进程回读，写账本还要落盘，
全部放主线程会让窗口假死。本文件分两段：

- **线程层**：`describe_error` / `JobContext` / `RightMenuTask` / `TaskGroup`
- **任务层**：`xxx_worker(ctx, ...)`，签名固定 `worker(ctx) -> object`

本文件**只做线程封装**：一个 worker 就一行——取模块属性调操作层、原样返回结果。注册表
键名、提权白名单、账本字段全在操作层（`scan`/`shellnew`/`ops`/`classic`/`custom`/
`yzmenu`/`store`）里，本层既不拼路径也不拼命令。

**调用时取模块属性**：顶部 `from . import ...` 只绑模块，函数体内按 `store.xxx()` 调用
——`from .store import restore_all` 那样的直接绑定会在 import 时把名字钉死，UI 测试的
monkeypatch 拦截不到（与 `ops.py` 同一条纪律）。

线程收口三重保险（缺一条 pytest 就会挂在悬挂线程上）：`settled` 排队执行 `_on_settled` →
`quit()`+`wait()`+`_retire()`；页面 `destroyed` → `shutdown()`；QThread 挂在 TaskGroup parent
上。`_retire` 见其 docstring：缺它那一步会 abort。"""
import threading

from core.qt_bootstrap import import_qt

from . import classic, custom, ops, scan, shellnew, store, yzmenu

_, QtCore, _QtGui, _QtWidgets = import_qt()

#: shutdown 时 join 的超时（ms），超了就 terminate 兜底
_JOIN_MS = 4000


def _retire(task):
    """销毁已 join 完的 QThread——**必须当场送达**，不能只 `deleteLater()`。

    `deleteLater()` 只是往队列投一条 DeferredDelete。若此后 TaskGroup 先被 GC 掉（测试出
    作用域或页面重建），`~QObject` 连带释放子 QThread，那条事件仍在队列里 → 下个
    `processEvents()` 写入已释放内存 → abort（崩溃点落在**后一个**测试，与出事者毫无栈关系）。
    故 `quit()+wait()` 后立刻 `sendPostedEvents` 投递干净——`proxy_ctrl` 缺此步，同样 abort。
    """
    task.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(task, QtCore.QEvent.DeferredDelete)


def describe_error(exc):
    """任意异常 → (分类, 可读文案)。键路径可以出现，**任何值原文都不写进文案**。

    `PermissionError` 是 `OSError` 子类，**必须先判**，否则权限错误会被错分到 io
    （两者给用户的下一步动作完全不同：改权限 vs 重试/查安全软件）。
    """
    if isinstance(exc, PermissionError):
        return "permission", f"权限不足：{exc}"
    if isinstance(exc, OSError):
        return "io", f"系统调用失败：{exc}"
    if isinstance(exc, ValueError):
        return "invalid", f"参数不合法：{exc}"
    return "unknown", f"未预期的错误：{exc}"


class JobContext:
    """传给任务层的句柄：取消标志 + 进度回调。

    抽出来是为了让任务层不依赖 Qt——UI 侧只需一个 `progress` 回调，两边都不必知道
    QThread 的存在。
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
        """转发进度。UI 回调抛异常绝不能中断后台任务。"""
        if self._on_progress is None:
            return
        try:
            self._on_progress(done, total)
        except Exception:
            pass


class RightMenuTask(QtCore.QThread):
    """后台跑 `worker(JobContext) -> object`。

    成功发 `succeeded(result)`、失败发 `failed(分类, 文案)`，最后都发 `settled()`
    （供 UI 解除 busy + 收口线程）。被 `stop()` 后不再发结果信号，但 `settled()` 照发。
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
        """请求中断：置停止位并置位 cancel 事件（worker / 操作层会读到它）。"""
        self._stopped = True
        self.ctx.request_cancel()

    def run(self):
        try:
            result = self._worker(self.ctx)
            if not self._stopped:
                self.succeeded.emit(result)
        except Exception as exc:                     # noqa: BLE001 - 兜底成 UI 文案
            if not self._stopped:
                kind, text = describe_error(exc)
                self.failed.emit(kind, text)
        finally:
            self.settled.emit()


class TaskGroup(QtCore.QObject):
    """串行化一批 RightMenuTask：忙时拒绝新任务，结束即收口，关闭时全部中断。

    串行而非并行是刻意的：注册表写与账本写必须成对串行，交错会让「写 → 回读 →
    记账本」的时序各写一遍并互相漂移（与 ops 的单写网关同一条纪律）。
    """

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
        task = RightMenuTask(worker, label=label, on_progress=on_progress, parent=self)
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


# ── 任务层：薄封装，一个 worker 一行（结果原样透传给 UI 渲染）────────────

def scan_scope_worker(ctx, backend, scope):
    """扫描某一级菜单（`"root"` / 扩展名 / CLSID…）→ item 列表。"""
    return scan.scan_scope(backend, scope)


def scan_shellnew_worker(ctx, backend):
    """扫描「新建」菜单 → item 列表（含扩展名→处理程序映射）。"""
    return shellnew.scan_shellnew(backend)


def apply_op_worker(ctx, backend, op):
    """隐藏/还原/删除三个原语动作 → `{"ok","detail"}`。HKLM 写自动走提权作业。"""
    return ops.apply_op(backend, op)


def classic_state_worker(ctx, backend):
    """经典右键菜单当前状态 → `"enabled"` / `"disabled"` / `"unknown"`。"""
    return classic.get_classic_state(backend)


def classic_set_worker(ctx, backend, enable):
    """开启/还原经典右键菜单 → `{"ok","detail"}`（两条路径各自只写自己的键）。"""
    return classic.enable_classic(backend) if enable else classic.disable_classic(backend)


def save_item_worker(ctx, backend, item):
    """新增/更新一个自定义菜单项（含子项）→ `{"ok","detail"}`。"""
    return custom.save_item(backend, item)


def delete_item_worker(ctx, backend, item_id):
    """按 id 删除自定义菜单项及其全部注册表投影 → `{"ok","detail"}`。"""
    return custom.delete_item(backend, item_id)


def yzmenu_state_worker(ctx, backend):
    """「YZplan 子菜单」装没装 + 挂了哪些已知动作 → `{"installed","actions"}`。"""
    return yzmenu.get_yzmenu_state(backend)


def yzmenu_install_worker(ctx, backend, actions):
    """安装「YZplan 子菜单」→ `{"ok","detail"}`。

    `{"ok": False, "detail": "至少选择一个动作"}` 是**正常返回值而非异常**（`yzmenu
    ._validate` 在任何写入之前就拒掉空清单），UI 当普通失败提示展示即可。
    """
    return yzmenu.install_yzmenu(backend, actions)


def restore_all_worker(ctx, backend):
    """一键还原账本记下的每一类改动 → `{"ok","report"}`（逐条结果都在 report 里）。"""
    return store.restore_all(backend)
