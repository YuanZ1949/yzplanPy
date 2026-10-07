"""层 B：全模块无头冒烟（规范 docs/功能自动化验证规范.md §4-B）。

目的：任何模块在 offscreen 下无法被注册表发现、无法实例化、无法构造三种
UI 钩子、或无法完成 start()/stop() 生命周期，都要在这里**显式失败**——
绝不做静默 skip（规范 §4-B 硬性决定）。这层是「程序整体还能不能起来」的
最廉价门禁：真机上每个按钮都点一遍的成本太高，先把「模块能加载并能建出
界面」这条底线钉死。

隔离要点（真实副作用，见各 module.py 的 start()）：
- config 走临时 AppConfig（绝不写生产 settings.json）；`webview.blocked_hosts`
  置空，确保 webview_control 的监控线程 ``kill_host_webview([])`` 不会误杀
  开发机上的真实 webview2 进程。
- webview_control 的监控线程会调 ``gc.disable()``（模块设计如此，防 Qt 对象
  被 GC 回收）；teardown 必须 ``gc.enable()`` 还原，否则污染同进程后续测试。
- DB 隔离由 conftest._isolate_db 统一完成。
"""
import gc

import pytest

# 注册表实际应发现的模块 id（= REGISTRY._modules 的 key）。
# 注意：目录名 ≠ 模块 id！`modules/perf_monitor/` 的模块 id 是
# `performance_meter`（见 perf_monitor/module.py 的 MODULE_INFO/MODULE_ID）。
# 新增模块必须同步加到这里——否则 test_registry_discovers_all_modules 会以
# 「未登记」失败，逼迫维护者显式把新模块纳入冒烟范围。
EXPECTED_MODULES = frozenset({
    "path_forward",
    "blog",
    "proxy_ctrl",
    "performance_meter",
    "sys_info",
    "router_admin",
    "rss_aggregator",
    "right_menu",
    "screenshot",
    "todo_notes",
    "win_maintenance",
    "webview_control",
    "translator",
})

_SKIP_PKG = {"__init__", "base", "registry"}


def _qt_widgets():
    from core.qt_bootstrap import import_qt
    # import_qt() -> (PySide6, QtCore, QtGui, QtWidgets)
    _, _QtCore, _QtGui, QtWidgets = import_qt()
    return QtWidgets


def _scan_module_infos():
    """按注册表同款发现方式扫描 modules/ 下的包顶层 MODULE_INFO。

    返回 {module_id: MODULE_INFO}。这条链路正是注册表判定「是不是模块」
    的依据（缺 MODULE_INFO 或 Module 就静默跳过），这里把它显式化以便断言。
    """
    import importlib
    import pkgutil

    import modules as pkg

    infos = {}
    for entry in pkgutil.iter_modules(pkg.__path__, f"{pkg.__name__}."):
        short = entry.name.rsplit(".", 1)[-1]
        if short in _SKIP_PKG:
            continue
        mod = importlib.import_module(f"modules.{short}")
        info = getattr(mod, "MODULE_INFO", None)
        if isinstance(info, dict) and info.get("id"):
            infos[info["id"]] = info
    return infos


@pytest.fixture
def smoke(tmp_path, qapp):
    """真实 ModuleRegistry + 临时 config + 无头父窗口。

    真实（而非 fake）是这层的意义：只有真实注册表才会暴露「某模块 import
    就炸、MODULE_INFO 写错、create_page 依赖真实环境」这类问题。
    """
    from core.config import AppConfig
    from modules.registry import ModuleContext, ModuleRegistry

    QtWidgets = _qt_widgets()
    cfg = AppConfig(path=str(tmp_path / "smoke_settings.json"))
    # 空拦截清单：webview 监控不会杀任何进程。
    cfg.set("webview.blocked_hosts", [])
    host = QtWidgets.QWidget()

    ctx = ModuleContext(cfg, host, qapp)
    reg = ModuleRegistry(ctx)
    ctx.registry = reg  # 部分代码可能经 context 反查注册表

    infos = _scan_module_infos()
    try:
        yield reg, host, QtWidgets, infos
    finally:
        try:
            reg.stop_all()
        finally:
            host.deleteLater()
            qapp.processEvents()
            gc.enable()  # 抵消 webview_control 监控线程的 gc.disable()


def test_registry_discovers_all_modules(smoke):
    """注册表加载是「静默吞异常」的（registry._load_all 只 print）——
    这里把缺失项变成硬失败，否则一个模块炸了整程序却悄无声息。"""
    reg, _host, _w, _infos = smoke
    ids = {m.id for m in reg.all()}
    missing = EXPECTED_MODULES - ids
    unexpected = ids - EXPECTED_MODULES
    assert not missing, f"模块加载失败（注册表静默吞异常）: {sorted(missing)}"
    assert not unexpected, f"新增模块未登记到冒烟清单: {sorted(unexpected)}"


@pytest.mark.parametrize("mid", sorted(EXPECTED_MODULES))
def test_module_metadata_contract(smoke, mid):
    """元数据契约：包级 MODULE_INFO.id == 类级 MODULE_ID == 实例 id。"""
    reg, _host, _w, infos = smoke
    mod = reg.get(mid)
    assert mod is not None, f"{mid} 未能实例化"
    assert mid in infos, f"{mid} 无可用的模块级 MODULE_INFO"
    info = infos[mid]
    assert info.get("name"), f"{mid}.MODULE_INFO 缺少 name"
    assert info.get("description"), f"{mid}.MODULE_INFO 缺少 description"
    assert mod.MODULE_ID == mid, f"{mid}.MODULE_ID={mod.MODULE_ID!r} 与 id 不一致"
    assert mod.id == mid
    assert mod.MODULE_NAME, f"{mid}.MODULE_NAME 为空"


@pytest.mark.parametrize("mid", sorted(EXPECTED_MODULES))
def test_module_ui_hooks_headless(smoke, mid):
    """三种 UI 钩子都必须能在 offscreen 下构造（返回 None 或 QWidget）。"""
    reg, host, QtWidgets, _infos = smoke
    mod = reg.get(mid)
    assert mod is not None, f"{mid} 未能实例化"
    for factory in (mod.create_home_widget,
                    mod.create_settings_widget,
                    mod.create_page):
        widget = factory(host)
        assert widget is None or isinstance(widget, QtWidgets.QWidget), (
            f"{mid}.{factory.__name__} 返回非 QWidget: {type(widget)!r}")


@pytest.mark.parametrize("mid", sorted(EXPECTED_MODULES))
def test_module_lifecycle_start_stop(smoke, mid):
    """start()/stop() 必须无异常并正确翻转 running 状态。"""
    reg, _host, _w, _infos = smoke
    mod = reg.get(mid)
    assert mod is not None, f"{mid} 未能实例化"
    mod.start()
    assert mod.running is True, f"{mid}.start() 未置 running=True"
    mod.stop()
    assert mod.running is False, f"{mid}.stop() 未置 running=False"
