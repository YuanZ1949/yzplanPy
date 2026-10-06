"""tests/test_module_logging.py: 未接入主日志模块的 logger 接入契约。

背景（router「未预期的错误」排查）：三个 workers.py 的 catch-all 只把文案 emit 给
UI，不打印、不落日志、不留 traceback——`yzplan.log` 里查不到任何痕迹，异常发生后
无法回溯。5 个模块（router_admin / proxy_ctrl / right_menu / perf_monitor /
todo_notes）也完全没接 getLogger，生命周期在主日志中不可见。

本文件锁定两条改造：
1. 三个 workers.py 的 catch-all 必须以 ERROR + exc_info 落进日志（→ yzplan.log
   + GUI 错误计数 + stderr.log 三处可见）；分类失败必须落 WARNING；
2. 5 个原日志黑洞模块的 start()/stop() 必须打 INFO 生命周期日志。
"""
import importlib
import logging

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


class _FakeConfig:
    """最小配置替身（与 test_proxy_ui / test_router_ui 同模式）。"""

    def __init__(self):
        self.settings = {}

    def module_setting(self, module_id, key, default=None):
        return self.settings.get((module_id, key), default)

    def set_module_config(self, module_id, cfg):
        self.settings[(module_id, "__cfg__")] = cfg

    def get(self, key, default=None):
        return default

    def set(self, key, value):
        return True


class _FakeContext:
    def __init__(self):
        self.config = _FakeConfig()
        self.host_window = None
        self.app = None

    def module_setting(self, module_id, key, default=None):
        return self.config.module_setting(module_id, key, default)

    def set_module_config(self, module_id, cfg):
        return self.config.set_module_config(module_id, cfg)


# QApplication 一律用 tests/conftest.py 的 session 级 `qapp` fixture（AGENTS.md 规则 3）。


def _records_from(caplog, logger_name):
    return [r for r in caplog.records if r.name == logger_name]


def _run_and_collect(task, worker_result_target):
    """把 failed 信号收集进列表，同步跑 task.run()（不 start 线程）。"""
    task.failed.connect(lambda kind, text: worker_result_target.append((kind, text)))
    task.run()
    return worker_result_target


# ── 1. workers catch-all：未预期异常必须落 ERROR + traceback ──────────

def test_router_task_unknown_failure_logs_exception(caplog, monkeypatch, qapp):
    from modules.router_admin import workers
    from modules.router_admin.connection import ConnectionParams

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        def open(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(workers, "TelnetSession", _FakeSession)

    def _boom(session):
        raise RuntimeError("boom-from-router")

    task = workers.RouterTask(ConnectionParams(), _boom, label="overview")
    got = _run_and_collect(task, [])

    # UI 文案路径保持原样
    assert got and got[0][0] == "unknown"
    assert "未预期的错误：boom-from-router" in got[0][1]

    # 新契约：ERROR + exc_info 落进主日志（caplog 按 logger 名过滤）
    recs = _records_from(caplog, "modules.router_admin.workers")
    errors = [r for r in recs if r.levelno >= logging.ERROR]
    assert errors, "workers catch-all 必须把未预期异常以 ERROR 写进主日志"
    assert errors[0].exc_info is not None, "必须携带 traceback（exc_info）"
    assert errors[0].exc_info[0] is RuntimeError
    assert "boom-from-router" in str(errors[0].exc_info[1])


def test_proxy_task_unknown_failure_logs_exception(caplog, qapp):
    from modules.proxy_ctrl import workers

    def _boom(ctx):
        raise RuntimeError("boom-from-proxy")

    task = workers.ProxyTask(_boom, label="scan")
    got = _run_and_collect(task, [])

    assert got and got[0][0] == "unknown"
    assert "boom-from-proxy" in got[0][1]

    recs = _records_from(caplog, "modules.proxy_ctrl.workers")
    errors = [r for r in recs if r.levelno >= logging.ERROR]
    assert errors, "proxy workers catch-all 必须落 ERROR"
    assert errors[0].exc_info is not None
    assert "boom-from-proxy" in str(errors[0].exc_info[1])


def test_right_menu_task_unknown_failure_logs_exception(caplog, qapp):
    from modules.right_menu import workers

    def _boom(ctx):
        raise RuntimeError("boom-from-rightmenu")

    task = workers.RightMenuTask(_boom, label="scan")
    got = _run_and_collect(task, [])

    assert got and got[0][0] == "unknown"
    assert "boom-from-rightmenu" in got[0][1]

    recs = _records_from(caplog, "modules.right_menu.workers")
    errors = [r for r in recs if r.levelno >= logging.ERROR]
    assert errors, "right_menu workers catch-all 必须落 ERROR"
    assert errors[0].exc_info is not None
    assert "boom-from-rightmenu" in str(errors[0].exc_info[1])


# ── 2. workers 分类失败：必须落 WARNING（不丢痕迹，但不算程序错误）───

def test_router_task_classified_failure_logs_warning(caplog, monkeypatch, qapp):
    from modules.router_admin import workers
    from modules.router_admin.connection import ConnectionParams
    from modules.router_admin.telnet import TelnetLoginError

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        def open(self):
            raise TelnetLoginError("认证失败：路由器拒绝了该口令")

        def close(self):
            pass

    monkeypatch.setattr(workers, "TelnetSession", _FakeSession)
    task = workers.RouterTask(ConnectionParams(), lambda s: None, label="overview")
    got = _run_and_collect(task, [])

    assert got and got[0][0] == "login"          # 分类文案路径不变
    recs = _records_from(caplog, "modules.router_admin.workers")
    warnings = [r for r in recs if r.levelno == logging.WARNING]
    assert warnings, "分类失败必须落 WARNING"
    assert not [r for r in recs if r.levelno >= logging.ERROR]


def test_proxy_task_classified_failure_logs_warning(caplog, qapp):
    from modules.proxy_ctrl import workers

    def _bad(ctx):
        raise ValueError("参数不合法")

    task = workers.ProxyTask(_bad, label="apply")
    got = _run_and_collect(task, [])

    assert got and got[0][0] == "invalid"
    recs = _records_from(caplog, "modules.proxy_ctrl.workers")
    assert [r for r in recs if r.levelno == logging.WARNING], "分类失败必须落 WARNING"
    assert not [r for r in recs if r.levelno >= logging.ERROR]


def test_right_menu_task_classified_failure_logs_warning(caplog, qapp):
    from modules.right_menu import workers

    def _bad(ctx):
        raise PermissionError("拒绝访问")

    task = workers.RightMenuTask(_bad, label="hide")
    got = _run_and_collect(task, [])

    assert got and got[0][0] == "permission"
    recs = _records_from(caplog, "modules.right_menu.workers")
    assert [r for r in recs if r.levelno == logging.WARNING], "分类失败必须落 WARNING"
    assert not [r for r in recs if r.levelno >= logging.ERROR]


# ── 3. 5 个原日志黑洞模块：start()/stop() 必须留 INFO 生命周期日志 ────

@pytest.mark.parametrize("pkg_name", [
    "modules.router_admin",
    "modules.proxy_ctrl",
    "modules.right_menu",
    "modules.perf_monitor",
    "modules.todo_notes",
])
def test_module_lifecycle_logged(pkg_name, caplog, qapp, monkeypatch, tmp_path):
    # 持久化资源隔离（AGENTS.md 规则 7）：todo_notes 的 SQLite 走 conftest
    # _isolate_db；right_menu/proxy 的 store 路径同样在 conftest 中重定向。
    pkg = importlib.import_module(pkg_name)
    module = pkg.Module(_FakeContext())
    logger_name = f"{pkg_name}.module"

    with caplog.at_level(logging.INFO, logger=logger_name):
        module.start()
        module.stop()

    msgs = [r.getMessage() for r in _records_from(caplog, logger_name)]
    assert any("启动" in m for m in msgs), f"{pkg_name}.module 必须在 start 打 INFO 启动日志"
    assert any("停止" in m for m in msgs), f"{pkg_name}.module 必须在 stop 打 INFO 停止日志"
