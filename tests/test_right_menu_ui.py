"""right_menu 模块契约：包骨架与惰性导出。"""
import importlib
import os
import subprocess
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 惰性导出的真实不变式分两层，都在【全新解释器子进程】里断言：
#   1. import modules.right_menu 不得急切导入子模块 modules.right_menu.module；
#   2. 无论包导入还是 module.py 自身的导入，都不得把 PySide6/shiboken 拉进
#      sys.modules —— widgets 的 import 必须留在 create_home_widget/
#      create_page 函数体内。
# 原因：registry 的模块发现（getattr(MODULE_INFO)+getattr(Module)）必须能在任何
# Qt 导入之前完成——本应用预留的 --elevated-job 提权作业通道（后续接入）会在
# 一切 Qt import 之前走模块发现。届时若 Qt 已被拖入，该通道会付出无谓代价。
# 注意惰性代理的真实作用边界：getattr 取值必然触发代理、进而加载 module.py，
# 代理保证的是「纯 Python 操作层 import modules.right_menu.elevate 这类路径不会
# 加载 module.py」，所以 module.py 自身 Qt-free 是第二条独立的必需条件。
# 第 2 条必须单独 import module.py 才能覆盖：惰性代理下包导入根本不加载它。
#
# 断言在【全新解释器子进程】里做：本文件里 test_module_info_contract 已经
# 通过代理取过值，modules.right_menu.module 早就在 sys.modules 中；qapp
# fixture 也已加载 PySide6。进程内断言会对收集/执行顺序敏感而误报，
# 同 tests/test_lazy_webengine.py 的处理方式。
_FRESH_PROCESS_CHECK = r"""
import os
import sys

sys.path.insert(0, os.environ["YZPLAN_PROJECT_ROOT"])


def _qt_modules():
    return sorted(n for n in sys.modules if n.startswith(("PySide6", "shiboken")))


# 阶段 1：只 import 包本身 —— 不得急切导入子模块，也不得泄漏 Qt。
import modules.right_menu

if "modules.right_menu.module" in sys.modules:
    sys.stderr.write("EAGER_SUBMODULE:modules.right_menu.module")
    sys.exit(1)

_leaked = _qt_modules()
if _leaked:
    sys.stderr.write("QT_LEAKED:" + ",".join(_leaked))
    sys.exit(1)

# 阶段 2：import 子模块 module.py 本身也不得引入 Qt —— widgets 的 import
# 必须留在 create_home_widget/create_page 函数体内，绝不放模块顶层。
# 阶段 1 覆盖不到这一点：惰性代理下包导入根本不加载 module.py。
import modules.right_menu.module

_leaked = _qt_modules()
if _leaked:
    sys.stderr.write("QT_LEAKED_BY_MODULE:" + ",".join(_leaked))
    sys.exit(1)

sys.exit(0)
"""


def test_module_info_contract():
    mod = importlib.import_module("modules.right_menu")
    assert mod.MODULE_INFO["id"] == "right_menu"
    assert mod.MODULE_INFO["name"] and mod.MODULE_INFO["description"]
    assert issubclass(mod.Module, __import__("modules.base", fromlist=["ModuleBase"]).ModuleBase)
    assert mod.Module.MODULE_ID == "right_menu"


def test_lazy_export_stays_qt_free_in_fresh_process():
    """PEP 562 惰性代理：包导入不得急切导入子模块或泄漏 Qt。"""
    env = dict(os.environ)
    env["YZPLAN_PROJECT_ROOT"] = _PROJECT_ROOT
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS_CHECK],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if proc.returncode == 0:
        return
    if "EAGER_SUBMODULE:" in proc.stderr or "QT_LEAKED:" in proc.stderr or "QT_LEAKED_BY_MODULE:" in proc.stderr:
        pytest.fail(
            "modules.right_menu 的惰性导出被破坏（包顶层急切导入）：\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
    # 非惰性违规类失败（环境故障）——向上抛，避免把环境故障误判为"通过"。
    raise RuntimeError(
        "子进程惰性检查失败（非惰性导出违规）：\n"
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


def test_unknown_attribute_raises():
    """惰性代理只认 MODULE_INFO / Module，其余按 PEP 562 抛 AttributeError。"""
    mod = importlib.import_module("modules.right_menu")
    with pytest.raises(AttributeError):
        mod.definitely_not_exported


def test_task_group_runs_worker_and_settles(qapp):
    import time
    from modules.right_menu.workers import TaskGroup, describe_error
    done = {}
    g = TaskGroup()
    assert g.start(lambda ctx: {"v": 1}, on_ok=lambda r: done.update(r), label="t")
    deadline = time.time() + 5
    while g.busy and time.time() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    assert done.get("v") == 1
    # 分类判序钉死：`PermissionError` 是 `OSError` 子类，两个 isinstance 分支一旦调换
    # 顺序，权限错误就会落进 io 类别，而「改权限」与「重试/查安全软件」给用户的下一步
    # 动作完全不同——所以 PermissionError 与 OSError 必须各有一条独立断言。
    assert describe_error(ValueError("bad"))[0] == "invalid"
    assert describe_error(PermissionError("x"))[0] == "permission"
    assert describe_error(OSError("x"))[0] == "io"
    assert describe_error(RuntimeError("x"))[0] == "unknown"


def test_task_group_rejects_when_busy(qapp):
    import time
    from modules.right_menu.workers import TaskGroup
    g = TaskGroup()
    g.start(lambda ctx: (time.sleep(0.2), {"v": 1})[1])
    assert g.start(lambda ctx: {"v": 2}) is False
    deadline = time.time() + 5
    while g.busy and time.time() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    g.shutdown()


def test_page_shell_contract(qapp):
    from modules.right_menu.widgets.page import RightMenuPage
    from modules.right_menu.module import Module
    from modules.right_menu.registry_backend import FakeRegistry

    class _Ctx:  # 最小上下文（不建真窗口）
        config = None
        host_window = None
        app = qapp
        registry = None
        tray = None

    m = Module(_Ctx())
    page = RightMenuPage(m, parent=None, backend=FakeRegistry())
    try:
        assert page.frameless is True
        assert page.tabs.count() == 5                      # 五标签
        spec = page.title_bar_spec
        assert spec["widgets"] is False and len(spec["buttons"]) == 2
        assert page.scan is not None
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_scan_tab_scope_combo_and_filter(qapp):
    from modules.right_menu.widgets.page_tabs.scan_tab import ScanTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    group = TaskGroup()
    tab = ScanTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.combo_scope.count() == 4                # file/directory/background/drive
        rows = [{"display_name": "Alpha"}, {"display_name": "Beta"}]
        assert tab._filtered(rows)[0]["display_name"] == "Alpha"
        tab.edit_search.setText("bet")                     # 不区分大小写包含
        filtered = tab._filtered(rows)
        assert len(filtered) == 1 and filtered[0]["display_name"] == "Beta"
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_restore_marker_picks_existing_marker():
    """T6-M7：隐藏项只带 `disabled` 布尔，恢复必须回读实际存在的标记值名。

    直接写死 `name=None`（≡ LegacyDisable）会对「系统项用 ProgrammaticAccessOnly
    隐藏」的情况删错值名：标记没删掉，ops 却因回读 LegacyDisable 为 None 报成功。
    """
    from modules.right_menu.widgets.page_tabs.scan_tab import _restore_marker
    from modules.right_menu.registry_backend import FakeRegistry

    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\Demo", "ProgrammaticAccessOnly", "")
    row = {"hive": "hkcu", "key_path": r"Software\Classes\*\shell\Demo"}
    assert _restore_marker(r, row) == "ProgrammaticAccessOnly"
    r2 = FakeRegistry()
    r2.set("hkcu", r"Software\Classes\*\shell\Demo", "LegacyDisable", "")
    assert _restore_marker(r2, row) is None


def test_op_for_builds_full_op_dict_per_action():
    """`op_for` 是「行 + 动作 → ops.apply_op 的 op」唯一入口，三条分支都要钉死。

    重点是 restore 的 `name` 必须回读真实存在的标记值名（`ProgrammaticAccessOnly`），
    否则恢复会对系统项删错值名；而 disable 固定写 `LegacyDisable`（name=None），
    隐藏与还原往返才自洽。
    """
    from modules.right_menu.widgets.page_tabs import scan_rows
    from modules.right_menu.registry_backend import FakeRegistry

    reg = FakeRegistry()
    path = r"Software\Classes\*\shell\Demo"
    reg.set("hkcu", path, "ProgrammaticAccessOnly", "")
    row = {"hive": "hkcu", "key_path": path, "display_name": "Demo"}

    assert scan_rows.op_for("restore", reg, row) == {
        "action": "restore", "hive": "hkcu", "key_path": path,
        "name": "ProgrammaticAccessOnly"}
    assert scan_rows.op_for("disable", reg, row) == {
        "action": "disable", "hive": "hkcu", "key_path": path, "name": None}
    # 没有 ProgrammaticAccessOnly 的键：按 LegacyDisable（None）还原
    empty = FakeRegistry()
    assert scan_rows.op_for("restore", empty, row)["name"] is None

    # 纯格式化助手：按钮文字随 disabled、命令 60 字符截断、scope 中文映射
    assert scan_rows.action_label({"disabled": True}) == "恢复"
    assert scan_rows.action_label({"disabled": False}) == "隐藏"
    assert scan_rows.action_label({}) == "隐藏"          # 缺字段按未隐藏（.get 兜底）
    long_cmd = "x" * 80
    assert len(scan_rows.short(long_cmd)) == scan_rows.CMD_MAX
    assert scan_rows.short(long_cmd).endswith("…")
    assert scan_rows.short("short") == "short"
    assert scan_rows.scope_text("background") == "文件夹背景"
    assert scan_rows.scope_text("不存在的键") == "不存在的键"


def test_on_idle_refreshes_only_after_successful_op(qapp):
    """补刷链：写操作成功后推迟到 idle 刷一次；失败绝不刷。

    `on_ok` 跑在任务 settled **之前**（此刻 group 仍 busy，立刻 refresh 会被拒），所以
    成功只置 `_pending_refresh`，真正的 refresh 由 `on_idle()` 执行——这条链断掉
    的症状是「隐藏成功了但表格还是旧的『显示』胶囊」，纯 UI 层肉眼难察觉，必须测。
    """
    from modules.right_menu.widgets.page_tabs.scan_tab import ScanTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    group = TaskGroup()
    tab = ScanTab(None, group, parent=None, page=None, backend=FakeRegistry())
    calls = []
    try:
        tab.refresh = lambda *a, **k: calls.append("refresh")
        tab._on_op_result({"ok": True, "detail": "已完成: disable X"})
        assert tab._pending_refresh is True
        tab.on_idle()
        assert calls == ["refresh"]              # 成功 → 补刷恰一次
        assert tab._pending_refresh is False      # 标志已清，不会连刷
        tab.on_idle()
        assert calls == ["refresh"]              # 无新操作 → 不再刷

        tab._on_op_result({"ok": False, "detail": "写入未生效"})
        assert tab._pending_refresh is False
        tab.on_idle()
        assert calls == ["refresh"]              # 失败 → 不补刷（刷了也是旧状态）
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_home_summary_counts(tmp_path, monkeypatch):
    """`home_summary` 是纯函数：账本 + 经典状态 → 首页卡片三项。

    计数口径就是两个账桶的长度（`disabled` = 已隐藏的右键项、`custom_items` =
    自定义项），缺字段/None 必须降级为 0 而不是崩——首页没有失败态可展示。
    """
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import home_summary
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    st = rm_store._empty_state()
    st["disabled"].append({"hive": "hkcu", "key_path": "k", "name": None,
                           "original": None, "ts": "t"})
    st["custom_items"].append({"id": "1", "title": "T"})
    got = home_summary(st, "enabled")
    assert got == {"classic": "enabled", "disabled_count": 1, "custom_count": 1}
    # 缺字段/None 账桶 → 0（不是 len(None) 的 TypeError）
    assert home_summary({}, "unknown") == {"classic": "unknown",
                                           "disabled_count": 0, "custom_count": 0}
    assert home_summary({"disabled": None, "custom_items": None}, "enabled") == {
        "classic": "enabled", "disabled_count": 0, "custom_count": 0}


def test_home_widget_renders(qapp, tmp_path, monkeypatch):
    """首页小卡渲染：chip 文案按经典状态映射，两行计数来自账本。

    `classic_getter` 注入是硬要求：本卡的经典状态经 Win32Backend 读**真实注册表**，
    测试绝不允许碰真实注册表。断言用精确文案而非「非空」——默认的「未读取」也非空，
    只断言非空的话，「没读到状态」与「映射写错了」两种回归都会漏过去。
    """
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import RightMenuHomeWidget
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    w = RightMenuHomeWidget(None, parent=None, classic_getter=lambda be: "enabled")
    try:
        w._render()
        assert w.chip.text() == "经典菜单"          # enabled 的映射文案（≠ 默认「未读取」）
        assert w.lb_disabled.text() == "0"         # 空账本：STATE_PATH 不存在 → load 返空
        assert w.lb_custom.text() == "0"
    finally:
        w._stop()
        w.deleteLater()
        qapp.processEvents()


def test_home_widget_chip_maps_every_classic_state(qapp, tmp_path, monkeypatch):
    """三态映射逐条钉死：disabled / unknown 都不能掉回默认「未读取」。

    `unknown` 是 `classic.get_classic_state` 的合法返回值（这个 CLSID 被别的 COM
    注册占着），UI 必须显示「未知状态」而不是假装在经典或新版菜单上。
    """
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import RightMenuHomeWidget
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    seen = []
    for state, expected in (("enabled", "经典菜单"), ("disabled", "新版菜单"),
                            ("unknown", "未知状态"), ("weird", "未知状态")):
        w = RightMenuHomeWidget(None, parent=None,
                                classic_getter=lambda be, s=state: s)
        try:
            w._render()
            seen.append(w.chip.text())
            assert w.chip.text() == expected
        finally:
            w._stop()
            w.deleteLater()
            qapp.processEvents()
    assert seen == ["经典菜单", "新版菜单", "未知状态", "未知状态"]


def test_home_widget_tick_renders_synchronously(qapp, tmp_path, monkeypatch):
    """`tick()` 由 Module 定时器驱动：本卡数据全是本地读，直接同步渲染返 True。

    不起线程是刻意的（与 proxy_ctrl 卡相反，那张卡要起 git 子进程）——本卡的
    注册表读与 JSON 读都在毫秒级，为它起 QThread 反而多一层悬挂线程风险。
    """
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.home_widget import HOME_INTERVAL_MS, RightMenuHomeWidget
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    rm_store.save(rm_store._empty_state())          # 生成一份空账本文件
    w = RightMenuHomeWidget(None, parent=None, classic_getter=lambda be: "disabled")
    try:
        assert w.lb_disabled.text() == "0"         # 构造时那一轮的基线
        # 构造之后才写账本：tick() 必须真渲染一遍，否则计数仍是构造时的旧值
        state = rm_store.load()
        state["disabled"].append({"hive": "hkcu", "key_path": "k", "name": None,
                                  "original": None, "ts": "t"})
        state["custom_items"].append({"id": "1", "title": "T"})
        assert rm_store.save(state) is True
        assert w.tick() is True                     # 同步渲染：不等线程
        assert w.chip.text() == "新版菜单"
        assert w.lb_disabled.text() == "1"
        assert w.lb_custom.text() == "1"
    finally:
        w._stop()
        w.deleteLater()
        qapp.processEvents()
    assert HOME_INTERVAL_MS == 30000                # 首页刷新间隔（不是 proxy 的 60000）


def test_home_widget_injects_backend_into_classic_getter(qapp, tmp_path, monkeypatch):
    """注入的 backend 必须原样传给 `classic_getter`（页面/卡片共用同一后端视图）。

    `classic_getter` 拿到 None 或别的对象时，真实实现会退化成「读不到即 disabled」，
    而 classic_getter 型的测试永远发现不了——所以注入契约要单独钉一条。
    """
    from modules.right_menu import store as rm_store
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu.widgets.home_widget import RightMenuHomeWidget
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    backend = FakeRegistry()
    got = []
    w = RightMenuHomeWidget(None, parent=None, backend=backend,
                            classic_getter=lambda be: got.append(be) or "enabled")
    try:
        w._render()
        assert got and all(be is backend for be in got)
    finally:
        w._stop()
        w.deleteLater()
        qapp.processEvents()


def test_module_home_widget_and_timer_wiring(qapp, tmp_path, monkeypatch):
    """Module 侧接线：`create_home_widget` 建卡 + `start()` 建 30s 定时器。

    `stop()` 必须停表并解引用卡片，否则定时器会一直对已析构的 C++ 对象回调
    （RuntimeError）。经典状态经 `classic.get_classic_state` 默认值注入，
    故 monkeypatch 它即可让整条接线零真实注册表读写。
    """
    from modules.right_menu import classic as rm_classic
    from modules.right_menu import store as rm_store
    from modules.right_menu.module import Module
    from modules.right_menu.widgets.home_widget import HOME_INTERVAL_MS

    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_classic, "get_classic_state", lambda backend: "enabled")

    class _Ctx:  # 最小上下文（不建真窗口）
        config = None
        host_window = None
        app = qapp
        registry = None
        tray = None

    m = Module(_Ctx())
    assert m._home_widget is None and m._home_timer is None
    w = m.create_home_widget(None)
    try:
        assert w is not None
        assert m._home_widget is w
        assert w.chip.text() == "经典菜单"
        m.start()
        assert m._home_timer is not None
        assert m._home_timer.interval() == HOME_INTERVAL_MS
        m._home_tick()                              # 不抛：定时器回调路径通
        # 卡片销毁前必须还接在 Module 上：destroyed 钩子会把 _home_widget 解引用，
        # 没接上的话定时器会一直对已析构的 C++ 对象回调
        m._home_widget.tick = None
        w.destroyed.emit()
        assert m._home_widget is None
        assert m._home_timer is not None            # destroyed 只停表，不清 _home_timer
        m.stop()
        assert m._home_timer is None
        m.stop()                                    # 可重复调用
    finally:
        m.stop()                                    # 定时器必须停（否则活表对已析构对象回调）
        w._stop()
        w.deleteLater()
        qapp.processEvents()


def test_scan_tab_renders_action_button_per_row_state(qapp):
    """行渲染：操作列按钮文字必须逐行跟随 `disabled`（不是整表一份常量）。

    整表一份文字会让「已隐藏」的行仍显示「隐藏」（再点一次等于重复禁用）。
    """
    from core.qt_bootstrap import import_qt
    from modules.right_menu.widgets.page_tabs import scan_rows
    from modules.right_menu.widgets.page_tabs.scan_tab import ScanTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    _, _, _, QtWidgets = import_qt()
    rows = [{"hive": "hkcu", "key_path": r"Software\Classes\*\shell\A",
             "display_name": "A", "scope": "file", "command": "cmd-a",
             "disabled": False},
            {"hive": "hkcu", "key_path": r"Software\Classes\*\shell\B",
             "display_name": "B", "scope": "directory", "command": None,
             "disabled": True}]
    group = TaskGroup()
    tab = ScanTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        tab._apply_rows(rows)
        table = tab.table
        assert table.rowCount() == 2
        # 命令列：None 渲染成空串而不是 "None"
        assert table.item(0, scan_rows.COL_COMMAND).text() == "cmd-a"
        assert table.item(1, scan_rows.COL_COMMAND).text() == ""
        for index, expected in ((0, "隐藏"), (1, "恢复")):
            box = table.cellWidget(index, scan_rows.COL_ACTION)
            buttons = box.findChildren(QtWidgets.QToolButton)
            assert len(buttons) == 1 and buttons[0].text() == expected
        # 搜索过滤只影响渲染行数，不动按钮跟随关系
        tab.edit_search.setText("b")
        assert table.rowCount() == 1
        box = table.cellWidget(0, scan_rows.COL_ACTION)
        assert box.findChildren(QtWidgets.QToolButton)[0].text() == "恢复"
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_shellnew_tab_renders_rows(qapp):
    from modules.right_menu.widgets.page_tabs.shellnew_tab import ShellNewTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile", "")
    group = TaskGroup()
    tab = ShellNewTab(None, group, parent=None, page=None, backend=r)
    try:
        # values 用生产形状：scan_shellnew 给出的是 `[(值名, 值)]` 元组列表
        # （registry_backend.list_values 的返回形状），不是 dict。
        tab._apply_rows([{"hive": "hkcu", "ext": ".xyz", "kind": "null", "hidden": False,
                          "key_path": r"Software\Classes\.xyz\ShellNew", "template": None,
                          "values": [("NullFile", "")]}])
        assert tab.table.rowCount() == 1
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_shellnew_tab_action_buttons_per_row_state(qapp):
    """操作列必须**逐行**铺按钮：按钮组与文字都随 `(hive, hidden)` 变（不是整表一份常量）。

    三种行组合一次铺开：HKCU 未隐藏 → 隐藏+删除、HKCU 已隐藏 → 只给恢复、HKLM 未隐藏 →
    只给隐藏（系统项 `delete_shellnew` 直接拒绝，给了按钮也只会报「系统项仅支持隐藏」）。
    整表一份按钮会让「已隐藏」的行仍显示「隐藏」（再点一次等于重复隐藏）；漏了删除列则
    用户无法清理自己新建的项——两者都是肉眼可见的功能缺失，故逐行断言按钮文字与个数。
    """
    from core.qt_bootstrap import import_qt
    from modules.right_menu.widgets.page_tabs import shellnew_rows as rows
    from modules.right_menu.widgets.page_tabs.shellnew_tab import ShellNewTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    _, _, _, QtWidgets = import_qt()
    # 扩展名按升序排布：表格开着排序，若插入序与排序序不一致，重排行会让「按钮是否逐行
    # 跟随」的断言被掩盖（按钮与行错位），先排除这个干扰源。
    items = [{"hive": "hkcu", "ext": ".md", "kind": "null", "hidden": False,
              "key_path": r"Software\Classes\.md\ShellNew", "template": None,
              "values": [("NullFile", "")]},
             {"hive": "hkcu", "ext": ".txt", "kind": "template", "hidden": True,
              "key_path": r"Software\Classes\.txt\ShellNew",
              "template": r"C:\tpl.txt",
              "values": [("FileName__yzhidden", r"C:\tpl.txt")]},
             {"hive": "hklm", "ext": ".zzz", "kind": "data", "hidden": False,
              "key_path": r"Software\Classes\.zzz\ShellNew", "template": None,
              "values": [("Data", "x")]}]
    group = TaskGroup()
    tab = ShellNewTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab._apply_rows(items) == 3
        table = tab.table
        assert table.rowCount() == 3
        # 类型/状态胶囊的可见文案（kind → 中文映射错位或错列立刻红）
        for index, (kind_text, state_text) in enumerate(
                (("空文件", "显示"), ("模板", "已隐藏"), ("数据", "显示"))):
            assert table.cellWidget(index, rows.COL_KIND).text() == kind_text
            assert table.cellWidget(index, rows.COL_STATE).text() == state_text
        # 模板列渲染原文（截断交给 delegate，UI 层不做手工 short）
        assert table.item(1, 2).text() == r"C:\tpl.txt"
        # 操作列：三行三套按钮组
        for index, expected in enumerate((["隐藏", "删除"], ["恢复"], ["隐藏"])):
            box = table.cellWidget(index, rows.COL_ACTION)
            assert box is not None, f"第 {index} 行操作列没有按钮盒（铺错列了？）"
            buttons = box.findChildren(QtWidgets.QToolButton)
            assert [b.text() for b in buttons] == expected
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_shellnew_write_dispatch_routing_and_busy_guard(qapp):
    """写分派三条路径全钉死：`(动作, 行)` 路由到对应 shellnew 函数、confirm 取消即中止、
    group 忙时一律拒绝（不起线程、注册表零改动、按钮不置灰）。

    三段各自对应一类回归：
      * 路由——`_on_action` 必须按 `action` 分派；若一律当 hide，「恢复」会退化成重复隐藏
        （值名再加一次后缀，`restore_shellnew` 找不到配对值名而静默报「已恢复」，用户却
        什么也没恢复），而「删除」会变成隐藏。
      * confirm 取消——删除是本标签唯一不可逆的动作；确认框点「取消」若仍往下走就等于
        删掉了用户明确拒绝删的东西。
      * busy 守卫——`TaskGroup` 串行化是因为注册表写与账本写必须成对串行（交错的写→回读
        →记账本会把时序各写一遍并互相漂移）。
    """
    import time
    from modules.right_menu.widgets.page_tabs.shellnew_tab import ShellNewTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    path = r"Software\Classes\.md\ShellNew"
    r = FakeRegistry()
    r.set("hkcu", path, "NullFile", "")
    group = TaskGroup()
    tab = ShellNewTab(None, group, parent=None, page=None, backend=r)
    row = {"hive": "hkcu", "ext": ".md", "kind": "null", "hidden": False,
           "key_path": path, "template": None, "values": [("NullFile", "")]}
    try:
        # ── ① 路由 + confirm 缝（把 _start_write 换成记账桩，只观察「走到哪一步」）──
        started = []
        tab._start_write = lambda label, worker, hint: started.append(label) or True
        assert tab._on_action(("hide", row)) is True
        assert tab._on_action(("restore", row)) is True
        assert started == [f"shellnew:hide:{path}", f"shellnew:restore:{path}"]
        # 删除走同一条路，且必须真的问过确认框
        assert tab.delete_item(row, confirm_fn=lambda *a, **k: True) is True
        assert started[-1] == f"shellnew:delete:{path}"
        # 确认框点「取消」→ 中止，绝不进写路径
        assert tab.delete_item(row, confirm_fn=lambda *a, **k: False) is False
        assert len(started) == 3 and r.get("hkcu", path, "NullFile") == ""

        # ── ② busy 守卫：真占住 group，任何写动作都不得起线程 ──
        tab._start_write = ShellNewTab._start_write.__get__(tab)   # 还原真实现
        assert group.start(lambda ctx: time.sleep(0.3), label="占位") is True
        assert group.busy is True
        calls = []
        tab.refresh = lambda *a, **k: calls.append("refresh")
        # 用户在确认框点了「删除」，但上一项任务还在跑 → 拒绝
        assert tab.delete_item(row, confirm_fn=lambda *a, **k: True) is False
        assert "还在跑" in tab.hint.text()
        assert tab.btn_refresh.isEnabled()           # 没起任务就不该置灰
        assert r.get("hkcu", path, "NullFile") == ""  # 注册表零改动
        # 非删除动作（隐藏）同样被拒：写分派不能绕过 busy 守卫
        assert tab._on_action(("hide", row)) is False
        assert calls == []
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_shellnew_on_idle_refreshes_only_after_successful_write(qapp):
    """补刷链：写成功后推迟到 idle 刷一次；失败绝不刷（ShellNewTab 自己的一条链）。

    `on_ok` 跑在任务 settled **之前**（此刻 group 仍 busy，立刻 refresh 会被 `start` 拒），
    故成功只置 `_pending_refresh`，真正的 refresh 由 `on_idle()` 执行。链断掉的症状是
    「隐藏成功了但表格还是旧的『显示』胶囊」——纯 UI 层肉眼难察觉，必须测。
    """
    from modules.right_menu.widgets.page_tabs.shellnew_tab import ShellNewTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry

    group = TaskGroup()
    tab = ShellNewTab(None, group, parent=None, page=None, backend=FakeRegistry())
    calls = []
    try:
        tab.refresh = lambda *a, **k: calls.append("refresh")
        tab._on_op_result({"ok": True, "detail": "已隐藏"})
        assert tab._pending_refresh is True
        assert calls == []                       # on_ok 里绝不直接刷
        tab.on_idle()
        assert calls == ["refresh"]              # 成功 → 补刷恰一次
        assert tab._pending_refresh is False      # 标志已清，不会连刷
        tab.on_idle()
        assert calls == ["refresh"]              # 无新操作 → 不再刷
        tab._on_op_result({"ok": False, "detail": "写入未生效"})
        assert tab._pending_refresh is False
        tab.on_idle()
        assert calls == ["refresh"]              # 失败 → 不补刷（刷了也是旧状态）
        tab._on_op_result(None)                  # 畸形结果不得崩在 UI 线程
        assert tab._pending_refresh is False
    finally:
        group.shutdown()
        tab.deleteLater()
        qapp.processEvents()


def test_page_sync_enabled_reaches_both_real_tabs(qapp):
    """`group.idle` → `_sync_enabled` 必须把解禁转发给**两个**真标签（不止 scan）。

    只转发 scan 的话，shellnew 在一次写操作后按钮永不解禁、也永不做写后补刷；症状是
    「隐藏成功了但表格还是旧的『显示』胶囊」，且要连点几次才复现，肉眼极难归因。
    顺带钉住装配层：`shellnew` 落在第 2 个标签位、其余三个仍是占位（总数仍 5）。
    """
    from modules.right_menu.widgets.page import RightMenuPage
    from modules.right_menu.widgets.page_tabs import ShellNewTab
    from modules.right_menu.registry_backend import FakeRegistry

    page = RightMenuPage(None, parent=None, backend=FakeRegistry())
    try:
        assert page.tabs.count() == 5
        assert page.tabs.widget(1) is page.shellnew
        assert isinstance(page.tabs.widget(1), ShellNewTab)
        assert page.tabs.tabText(1) == "新建菜单"
        page.scan.btn_refresh.setEnabled(False)
        page.shellnew.btn_refresh.setEnabled(False)
        page._group.idle.emit()
        assert page.scan.btn_refresh.isEnabled()
        assert page.shellnew.btn_refresh.isEnabled()
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_shellnew_rows_chips_actions_and_call_time_write(monkeypatch):
    """`shellnew_rows` 纯逻辑层（Qt-free，本测试不碰 QApplication）：chips / 按钮 / 提示 / 写分派。

    这一层是「操作列铺什么、类型胶囊显示什么、提示说什么」的**唯一**决策点：它错了 UI 层
    没有任何编译期信号（按钮照铺、表格照画），只有直接断言纯函数才能把映射钉死——故本测试
    逐条钉死五 kind 的胶囊、三种行组合的按钮组、列下标与表头的一致性，以及 `write` 的
    「调用时取模块属性」纪律。
    """
    from modules.right_menu import shellnew
    from modules.right_menu.widgets.page_tabs import shellnew_rows as rows
    from modules.right_menu.registry_backend import FakeRegistry

    # 列下标必须与表头一一对应：错位会让操作按钮盖掉模板列/状态列
    assert rows.HEADERS == ("扩展名", "类型", "模板", "状态", "操作")
    assert (rows.COL_KIND, rows.COL_STATE, rows.COL_ACTION) == (1, 3, 4)
    # 五个 kind 逐条映射 + 未知 kind / 缺字段 / 非 dict 一律降级「未知」(error)
    assert [rows.kind_chip({"kind": k}) for k in
            ("null", "template", "data", "command", "unknown")] == [
        ("空文件", "info"), ("模板", "success"), ("数据", "info"),
        ("命令", "warning"), ("未知", "error")]
    for bogus in ({"kind": "第三方"}, {}, None, "不是 dict"):
        assert rows.kind_chip(bogus) == ("未知", "error")
    # 状态两态：已隐藏走警告色，仍显示走成功色
    assert rows.state_chip({"hidden": True}) == ("已隐藏", "warning")
    assert rows.state_chip({"hidden": False}) == ("显示", "success")
    assert rows.state_chip(None) == ("显示", "success")
    # actions_for 三种行组合：已隐藏只给恢复；HKCU 未隐藏才多一个删除；HKLM 不给删除
    hkcu_hidden = {"hive": "hkcu", "hidden": True}
    hkcu_open = {"hive": "hkcu", "hidden": False}
    hklm_open = {"hive": "hklm", "hidden": False}
    assert rows.actions_for(hkcu_hidden) == [("恢复", ("restore", hkcu_hidden))]
    assert rows.actions_for(hkcu_open) == [("隐藏", ("hide", hkcu_open)),
                                          ("删除", ("delete", hkcu_open))]
    assert rows.actions_for(hklm_open) == [("隐藏", ("hide", hklm_open))]
    # hive 大小写/空白不敏感（真实后端原样返回大小写）；畸形行不崩
    assert len(rows.actions_for({"hive": " HKCU "})) == 2
    assert rows.actions_for(None) == [("隐藏", ("hide", {}))]
    # 写动作名 → shellnew 函数名：缺一即 KeyError，说明白名单与实现漂了
    assert rows.WRITE_FNS == {"hide": "hide_shellnew", "restore": "restore_shellnew",
                              "delete": "delete_shellnew"}
    # 对话框下拉：下标 → kind，越界回退第一项（QComboBox 越界在本层不给信号）
    assert rows.ADD_KINDS == (("空文件", "null"), ("模板文件", "template"))
    assert [rows.add_kind(i) for i in (0, 1, 2, -1)] == ["null", "template", "null", "null"]
    # 提示文案：0 结果走含 HKLM 排查口径的 EMPTY_HINT，非 0 带计数
    assert rows.hint_for(0) == rows.EMPTY_HINT and "HKLM" in rows.EMPTY_HINT
    assert rows.hint_for(3) == "共 3 项；行尾可隐藏/恢复，HKCU 项还可删除。"
    assert rows.HINT_IDLE and "刷新" in rows.HINT_IDLE
    # write 必须在**调用时**取 shellnew 模块属性（import 期绑定会把名字钉死，monkeypatch
    # 拦不到「UAC 被取消」这类分支——这是 shellnew 包级纪律，UI 侧不能破）
    seen = []
    monkeypatch.setattr(shellnew, "hide_shellnew",
                        lambda be, item: seen.append((be, item)) or {"ok": True, "detail": "已隐藏"})
    backend, item = FakeRegistry(), {"hive": "hkcu", "key_path": "k"}
    assert rows.write("hide", backend, item) == {"ok": True, "detail": "已隐藏"}
    assert seen == [(backend, item)]
