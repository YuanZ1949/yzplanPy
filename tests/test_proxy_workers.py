"""tests/test_proxy_workers.py: proxy_ctrl 线程收口必须当场送达 DeferredDelete。

根因（right_menu/workers.py::_retire docstring 已立档，点名 proxy_ctrl 缺此步）：
`deleteLater()` 只投一条 DeferredDelete。若 TaskGroup 先被 GC，`~QObject` 连带释放
子 QThread，事件仍留在队列 → 下个 `processEvents()` 写已释放内存 → abort（崩溃点落在
**后一个**测试）。因此 `_on_settled` 与 `shutdown` 收口后，任务对象必须**立即**销毁，
不能等后续 processEvents。

断言手段：shiboken6.isValid() —— C++ 对象被当场删除则 Python 包装立即失效。
"""
import threading
import time

import pytest

from core.qt_bootstrap import import_qt
from modules.proxy_ctrl import workers

_, QtCore, QtGui, QtWidgets = import_qt()


def _is_valid(obj):
    import shiboken6
    return shiboken6.isValid(obj)


def test_on_settled_retires_task_immediately(qapp):
    """_on_settled 收口时任务必须已销毁（idle 发出的瞬间检查，早于下一轮 processEvents）。"""
    group = workers.TaskGroup()
    seen = []
    assert group.start(lambda ctx: 1)
    task = group._task
    assert task is not None
    group.idle.connect(lambda: seen.append(_is_valid(task)))

    deadline = time.monotonic() + 5.0
    while not seen and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert seen, "idle 信号未在 5s 内触发"
    assert seen[0] is False, (
        "idle 时任务对象仍存活：deleteLater 未被当场投递，"
        "DeferredDelete 残留队列会在后续 processEvents 写已释放内存（abort）"
    )


def test_shutdown_retires_task_immediately(qapp):
    """shutdown 同步收口后任务必须已销毁，且可重复调用。"""
    group = workers.TaskGroup()
    started = threading.Event()

    def worker(ctx):
        started.set()
        for _ in range(200):
            if ctx.cancelled:
                break
            time.sleep(0.02)
        return 1

    assert group.start(worker)
    task = group._task
    assert started.wait(5.0), "worker 未启动"
    group.shutdown()
    assert not _is_valid(task), "shutdown 后任务对象仍存活（缺 sendPostedEvents）"
    group.shutdown()  # 可重复调用
    assert not _is_valid(task)


def test_on_settled_keeps_idle_emission(qapp):
    """修复不得破坏既有行为：正常任务跑完后 group 回到 idle 且不 busy。"""
    group = workers.TaskGroup()
    fired = []
    group.idle.connect(lambda: fired.append(True))
    assert group.start(lambda ctx: 42)
    deadline = time.monotonic() + 5.0
    while not fired and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert fired, "idle 信号未触发"
    assert not group.busy


def test_task_success_path_keeps_contract(qapp):
    """任务层契约：成功路径 on_ok 收到结果，随后 group 回 idle（收口不吞信号）。"""
    group = workers.TaskGroup()
    results, idle = [], []
    group.on_success = lambda: None
    group.idle.connect(lambda: idle.append(True))
    assert group.start(lambda ctx: {"ok": True},
                       on_ok=results.append,
                       on_err=lambda k, t: pytest.fail(f"不应失败: {k}/{t}"))
    deadline = time.monotonic() + 5.0
    while not (results and idle) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert results == [{"ok": True}]
    assert idle
