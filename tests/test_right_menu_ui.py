"""right_menu 模块契约：包骨架与惰性导出。"""
import importlib
import os
import subprocess
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 编辑器 `value()` 必须给出的**完整** DOM 键集（spec §5.6）。写死成集合断言而不是逐个
#: `in`：`in` 断言对「少一个键」完全失明，而少键的后果是 `custom_dom.validate_item` 静默
#: 兜底、`custom.save_item` 拿不到 `id`/`scope` —— 只在真保存时才炸出来的数据丢失。
DOM_KEYS = {"id", "title", "icon", "scope", "ext_filter", "hive", "extended",
            "position", "action", "children"}

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


def test_page_sync_enabled_reaches_real_tabs(qapp):
    """`group.idle` → `_sync_enabled` 必须把解禁转发给**五个**真标签（不止 scan）。

    只转发 scan 的话，shellnew 在一次写操作后按钮永不解禁、也永不做写后补刷；症状是
    「隐藏成功了但表格还是旧的『显示』胶囊」，且要连点几次才复现，肉眼极难归因。
    顺带钉住装配层：`shellnew` 落在第 2 个标签位、`classic` 落在第 3 个、自定义项落在第 4 个、
    设置落在第 5 个——五个标签位各钉住具体类型（总数恒为 5，断言类型才防得住错位装配）。
    """
    from modules.right_menu.widgets.page import RightMenuPage
    from modules.right_menu.widgets.page_tabs import (ClassicTab, CustomTab, SettingsTab,
                                                       ShellNewTab)
    from modules.right_menu.registry_backend import FakeRegistry

    page = RightMenuPage(None, parent=None, backend=FakeRegistry())
    try:
        assert page.tabs.count() == 5
        assert page.tabs.widget(1) is page.shellnew
        assert isinstance(page.tabs.widget(1), ShellNewTab)
        assert page.tabs.tabText(1) == "新建菜单"
        assert page.tabs.widget(2) is page.classic
        assert isinstance(page.tabs.widget(2), ClassicTab)
        assert page.tabs.tabText(2) == "经典菜单"
        assert page.tabs.widget(3) is page.custom
        assert isinstance(page.tabs.widget(3), CustomTab)
        assert page.tabs.tabText(3) == "自定义项"
        # 最后一个标签位必须是设置真实现：五个标签位各钉住具体类型——只断言 count() == 5
        # 的话，两个标签被误装到同一位（总数照样是 5）这条装配不变量就是假的。
        assert page.tabs.tabText(4) == "设置"
        assert page.tabs.widget(4) is page.settings
        assert isinstance(page.tabs.widget(4), SettingsTab)
        page.scan.btn_refresh.setEnabled(False)
        page.shellnew.btn_refresh.setEnabled(False)
        page.classic.btn_toggle.setEnabled(False)
        page.custom.btn_refresh.setEnabled(False)
        page.settings.btn_restore.setEnabled(False)
        page._group.idle.emit()
        assert page.scan.btn_refresh.isEnabled()
        assert page.shellnew.btn_refresh.isEnabled()
        assert page.classic.btn_toggle.isEnabled()
        assert page.custom.btn_refresh.isEnabled()
        assert page.settings.btn_restore.isEnabled()
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


def test_classic_tab_toggle_roundtrip(qapp):
    from modules.right_menu.widgets.page_tabs.classic_tab import ClassicTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu import classic
    r = FakeRegistry()
    group = TaskGroup()
    tab = ClassicTab(None, group, parent=None, page=None, backend=r)
    try:
        assert classic.get_classic_state(r) == "disabled"
        ok = tab.toggle(confirm_fn=lambda *a, **k: True)   # 绕开模态确认
        deadline = __import__("time").time() + 5
        while group.busy and __import__("time").time() < deadline:
            qapp.processEvents()
        assert ok and classic.get_classic_state(r) == "enabled"
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_classic_tab_refresh_maps_states_and_toggle_back(qapp):
    """chip 三态映射 + 双向 toggle（enabled→关）。"""
    import time
    from modules.right_menu.widgets.page_tabs.classic_tab import ClassicTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu import classic
    r = FakeRegistry()
    group = TaskGroup()
    tab = ClassicTab(None, group, parent=None, page=None, backend=r)
    try:
        tab.refresh()
        assert tab.chip.text() == "新版菜单"          # 未开经典 = disabled 态
        # unknown：INPROC_KEY 下有值（键存在）但默认值为 None
        r.set("hkcu", classic.INPROC_KEY, "Other", "x")
        tab.refresh()
        assert tab.chip.text() == "未知状态"
        # 开经典 → chip 变「经典菜单」；再 toggle → 关回
        assert tab.toggle(confirm_fn=lambda *a, **k: True)
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        tab.refresh()
        assert tab.chip.text() == "经典菜单"
        assert tab.toggle(confirm_fn=lambda *a, **k: True)
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        tab.refresh()
        assert classic.get_classic_state(r) == "disabled"
        assert tab.chip.text() == "新版菜单"
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_classic_tab_restart_explorer_injects_and_cancels(qapp, monkeypatch):
    """重启资源管理器：confirm 拒绝→不起任务；确认→经注入缝调用（不 spawn 真进程）。"""
    import time
    from modules.right_menu.widgets.page_tabs import classic_tab as mod
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu import classic
    calls = []

    def fake_restart():
        calls.append("restart")
        return {"ok": True, "detail": "已重启资源管理器"}

    monkeypatch.setattr(classic, "restart_explorer", fake_restart)
    group = TaskGroup()
    tab = mod.ClassicTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.restart_explorer(confirm_fn=lambda *a, **k: False) is False
        assert not group.busy and calls == []      # 取消：不起任务
        assert tab.restart_explorer(confirm_fn=lambda *a, **k: True)
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        assert calls == ["restart"]
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_classic_tab_on_idle_refreshes_only_after_successful_toggle(qapp):
    """ClassicTab 一条链里的全部决策一次钉死：按钮文案跟随状态 / 胶囊换色要顶进布局 /
    busy 拒绝 / idle 解禁两个按钮 / 写后补刷只补一次且只在成功时补。

    五处回归的症状都落在「肉眼难察觉」那一侧，故只能靠直接断言把它们钉住：

      * **文案不跟随状态**：enabled 时仍显示「切换到经典菜单」的话，同一个按钮会让用户以为
        在重复开启，而真发出去的是 `disable_classic`——整棵删掉 CLSID 子树，会连别家软件
        （乃至系统自己）在同一位上的 COM 注册一起抹掉（破坏性路径）。
      * **胶囊换色不顶进布局**：`make_status_chip` 的色值写死在样式里，换色种只能新建一枚，
        新建后不 `replaceWidget` 就等于新胶囊根本没上线（旧的那枚还挂在行里，色种永远不变）。
      * **busy 守卫**：同一 `TaskGroup` 串行化是因为注册表写必须成对串行；守卫漏了就会让两个
        写交错，且拒绝时必须给提示而不是静默。
      * **`btn_restart` 不解禁**：重启一次之后按钮永久置灰，用户再也点不了第二次。
      * **补刷链**：`_on_toggle_ok` 跑在任务 settled **之前**（此刻 group 仍 busy），故成功只
        置 `_pending_refresh`，真正的 refresh 由 `on_idle()` 执行；断掉的症状是「切换成功了
        但胶囊/按钮文案还停在上一次的状态」，失败时多刷一次则纯属自欺（刷到的还是旧状态）。
    """
    import time
    from modules.right_menu import classic
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu.widgets.page_tabs.classic_tab import ClassicTab
    from modules.right_menu.workers import TaskGroup

    r = FakeRegistry()
    group = TaskGroup()
    tab = ClassicTab(None, group, parent=None, page=None, backend=r)
    calls = []
    try:
        # ── ① 文案跟随状态 + 胶囊换色顶进布局（disabled = info → enabled = warning）──
        assert classic.get_classic_state(r) == "disabled"
        assert tab.btn_toggle.text() == "切换到经典菜单"
        stale = tab._chip_row.itemAt(1).widget()      # 「当前风格」标签之后那枚胶囊
        r.set("hkcu", classic.INPROC_KEY, "", "")     # 写空默认值 = 经典菜单已开
        tab.refresh()
        assert tab.chip.text() == "经典菜单"
        assert tab.btn_toggle.text() == "恢复新版菜单"
        assert tab._chip_row.itemAt(1).widget() is tab.chip     # 新胶囊已在行内原位
        assert tab._chip_row.indexOf(stale) == -1               # 旧的已交出所有权
        assert tab._chip_row.indexOf(tab.chip) == 1

        # ── ② busy 拒绝：占住 group，切换不得起线程、注册表零改动 ──
        assert group.start(lambda ctx: time.sleep(0.3), label="占位") is True
        assert tab.toggle(confirm_fn=lambda *a, **k: True) is False
        assert "还在跑" in tab.hint.text()
        assert tab.btn_toggle.isEnabled()           # 没起任务就不该置灰
        assert classic.get_classic_state(r) == "enabled"
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents(); time.sleep(0.01)

        # ── ③ idle 解禁两个按钮 ──
        tab.btn_restart.setEnabled(False)
        tab.on_idle()
        assert tab.btn_restart.isEnabled()

        # ── ④ 补刷链：成功推迟到 idle 刷一次；失败/畸形结果绝不刷 ──
        tab.refresh = lambda *a, **k: calls.append("refresh")
        tab._on_toggle_ok({"ok": True, "detail": "已切换到经典菜单"})
        assert tab._pending_refresh is True and calls == []
        tab.on_idle()
        assert calls == ["refresh"]                  # 成功 → 补刷恰一次
        assert tab._pending_refresh is False
        tab.on_idle()
        assert calls == ["refresh"]                  # 无新操作 → 不再刷
        tab._on_toggle_ok({"ok": False, "detail": "写入未生效"})
        assert tab._pending_refresh is False         # 失败 → 不补刷（刷了也是旧状态）
        tab.on_idle()
        assert calls == ["refresh"]
        tab._on_toggle_ok(None)                      # 畸形结果不得崩在 UI 线程
        assert tab._pending_refresh is False
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_editor_dialog_keeps_nested_children_and_unexposed_fields(qapp):
    """I1：编辑含孙节点的条目，子树不得被拍平、一级子项的非 UI 字段不得被父表单覆盖。

    两条静默数据丢失都在这里：① UI 只画一层，`value()` 若像原来那样**从父表单重建**每个子
    项，孙节点会被整个丢掉——保存时 `custom._sync_item` 的 stale delete_tree 会先删掉它们的
    注册表投影，再把拍平的子树写回账本，用户点一次「确定」就再也找不回那层子菜单。
    ② 子项的 `kind`/`position`/`icon`/`extended`/`args` 在 UI 上根本没有控件，重建即等于
    「用默认值 + 父表单的值」覆写掉它们（`kind` 被改成父的 program、`args` 被改成父的参数）。

    修法是 copy-through：能对上原 id 的行从原 dict 深拷贝出发，只覆盖 UI 暴露的 title/target。
    """
    from modules.right_menu.custom import validate_item
    from modules.right_menu.widgets.editor_dialog import CustomItemDialog
    grand = {"id": "g1", "title": "孙项", "icon": "", "scope": "directory",
             "ext_filter": [], "hive": "hklm", "extended": False, "position": "bottom",
             "action": {"kind": "open", "target": r"C:\win.exe", "args": "", "workdir": ""},
             "children": []}
    child = {"id": "c1", "title": "子项", "icon": r"C:\i.ico", "scope": "file",
             "ext_filter": [".md"], "hive": "hklm", "extended": True, "position": "top",
             "action": {"kind": "open", "target": r"C:\old.exe", "args": "--legacy",
                        "workdir": r"C:\w"},
             "children": [grand]}
    item = {"id": "p1", "title": "父项", "icon": "", "scope": "file",
            "ext_filter": [".py"], "hive": "hkcu", "extended": False,
            "position": "default", "action": {"kind": "program", "target": "run.exe",
            "args": '"%1"', "workdir": ""}, "children": [child]}
    dlg = CustomItemDialog(None, item=item)
    try:
        kid = dlg.value()["children"][0]
        assert kid["id"] == "c1"                              # 一级子项 id 保留
        assert kid["icon"] == r"C:\i.ico"                     # 未暴露字段原样保留
        assert kid["position"] == "top" and kid["extended"] is True
        assert kid["action"]["kind"] == "open"                # 不被父表单的 program 覆盖
        assert kid["action"]["args"] == "--legacy"            # 不被父参数覆盖
        assert kid["action"]["workdir"] == r"C:\w"
        assert kid["ext_filter"] == [".md"]                   # 子项自己的扩展名不被覆盖
        assert kid["hive"] == "hklm" and grand["hive"] == "hklm"
        assert [g["id"] for g in kid["children"]] == ["g1"]    # 孙节点不丢
        assert kid["children"][0]["position"] == "bottom"
        assert validate_item(dlg.value())["ok"]
        # 改 UI 暴露的两个字段只改这两个：其余（含孙节点）逐字不动
        node = dlg.tree.topLevelItem(0)
        node.setText(0, "子项改名")
        node.setText(1, r"C:\new.exe")
        moved = dlg.value()["children"][0]
        assert (moved["title"], moved["action"]["target"]) == ("子项改名", r"C:\new.exe")
        assert moved["id"] == "c1" and moved["action"]["args"] == "--legacy"
        assert [g["id"] for g in moved["children"]] == ["g1"]
        # 新加的行照现状新建（继承父的 scope/ext_filter/args，且没有孙节点）
        fresh = dlg.add_child()
        fresh.setText(0, "新子项")
        fresh.setText(1, "n.exe")
        dom = dlg.value()
        assert len(dom["children"]) == 2 and dom["children"][1]["action"]["args"] == '"%1"'
        assert dom["children"][1]["children"] == []
        assert validate_item(dom)["ok"]
        # 删掉的行才消失（孙节点随父子项一起被用户显式删掉，属预期）
        assert dlg.remove_child() is True
        assert len(dlg.value()["children"]) == 1
    finally:
        dlg.deleteLater(); qapp.processEvents()


def test_editor_dialog_preserves_original_hive(qapp):
    """I2：编辑已导入的 HKLM 条目，`value()` 必须保留 `hklm`，说明文字也不得再否认这件事。

    写死 `hive="hkcu"` 是「保存即搬家 + UAC 突现」两连击：旧投影按 hklm 分组走
    `elevate.run_job`（弹 UAC 等子进程回读），新项却写进 HKCU——用户没碰 hive，菜单却从全局
    挪到当前用户。对话框里没有 hive 控件，所以唯一正确的做法就是**原样带回去**。
    """
    from modules.right_menu.widgets import editor_dialog
    from modules.right_menu.widgets.editor_dialog import CustomItemDialog
    base = {"id": "m1", "title": "全局项", "icon": "", "scope": "file",
            "ext_filter": [".exe"], "hive": "hklm", "extended": False,
            "position": "default", "action": {"kind": "open", "target": r"C:\w.exe",
            "args": "", "workdir": ""}, "children": []}
    dlg = CustomItemDialog(None, item=base)
    extra = []
    try:
        assert dlg.value()["hive"] == "hklm"
        kid = dlg.add_child()
        kid.setText(0, "子")
        kid.setText(1, "s.exe")
        assert dlg.value()["children"][0]["hive"] == "hklm"   # 新子项跟随父的 hive
        # 认不出的 hive 一律按 HKCU 处理（绝不凭空写 HKLM，与 custom._hive 同一口径）
        for hive, want in ((" HKLM ", "hklm"), ("bogus", "hkcu"), ("", "hkcu")):
            probe = CustomItemDialog(None, item=dict(base, hive=hive))
            extra.append(probe)
            assert probe.value()["hive"] == want
        blank = CustomItemDialog(None, item={"hive": "hklm"})       # 缺键也不崩
        extra.append(blank)
        assert blank.value()["hive"] == "hklm"
        # 说明文字不得再声称「不会触碰 HKLM」（保留 hive 之后这句就是失实描述）
        assert "不会触碰 HKLM" not in editor_dialog._NOTE
    finally:
        for probe in extra:
            probe.deleteLater()
        dlg.deleteLater(); qapp.processEvents()


def test_editor_dialog_new_id_and_dom_keys_are_contract(qapp):
    """I4 的一半：新建路径的 id 与键集——`id` 写死成一个常量会让「每条新建项同身份」通过
    所有其他断言（`save_item` 靠 id upsert，同 id 的第二条会覆盖第一条，症状是建了三条却只
    剩一条），而键集少一个 `hive`/`children` 时 `in` 式断言完全失明。"""
    from modules.right_menu.custom import validate_item
    from modules.right_menu.widgets.editor_dialog import CustomItemDialog
    made = []
    try:
        for index in range(3):
            dlg = CustomItemDialog(None)
            made.append(dlg)
            ident = dlg.value()["id"]
            assert len(ident) == 8 and int(ident, 16) >= 0     # 8 位十六进制
            assert set(dlg.value()) == DOM_KEYS
        assert len({dlg.value()["id"] for dlg in made}) == 3, "三次新建必须拿到三个不同身份"
        # 填完目标后可直接保存：键集与编辑态一致，save_item / validate_item 靠的就是这些键
        made[-1].title_edit.setText("新建项")
        made[-1].target_edit.setText("run.exe")
        assert validate_item(made[-1].value())["ok"]
    finally:
        for dlg in made:
            dlg.deleteLater()
        qapp.processEvents()


def test_custom_tab_move_rejected_while_worker_runs(qapp, tmp_path, monkeypatch):
    """I3：lost update 守卫——worker 在跑时 `move()` 必须拒绝，且**不碰账本**。

    `move` 是本 Tab 唯一一个「同步改账本」的动作，而保存/导入 worker 正带着它自己读到的账本
    快照在跑：用户点一次「上移」，`move` 用**旧快照**写回整个 `custom_items`，worker 随后把
    自己那份（不含这次排序的）写回去——排序静默丢失。故守卫必须在**触碰账本之前**判 busy：
    `TaskGroup.start` 拒绝新任务靠的是「同一条 TaskGroup」，而 `move` 根本不起线程，绕过了
    那条防线，必须自己判一次。
    """
    import threading
    import time
    from modules.right_menu import store as rm_store
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu.widgets.page_tabs.custom_tab import CustomTab
    from modules.right_menu.workers import TaskGroup
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    a = {"id": "a1", "title": "A", "scope": "file", "ext_filter": [],
         "action": {"kind": "program", "target": "x", "args": "", "workdir": ""},
         "children": [], "icon": "", "hive": "hkcu", "extended": False, "position": "default"}
    b = dict(a, id="b2", title="B")
    rm_store.set_custom_items([a, b])
    group = TaskGroup()
    tab = CustomTab(None, group, parent=None, page=None, backend=FakeRegistry())
    gate, running = threading.Event(), threading.Event()
    try:
        def blocker(ctx):
            running.set()
            gate.wait(5)
            return {"ok": True, "detail": "占位"}
        assert group.start(blocker, label="占位") is True
        assert running.wait(5) and group.busy is True
        assert tab.move("b2", -1) is False                    # 忙 → 拒绝
        assert "还在跑" in tab.hint.text()                    # 必须给提示而非静默
        assert [i["id"] for i in rm_store.get_custom_items()] == ["a1", "b2"]  # 账本零改动
        assert tab._on_action(("move_up", "b2")) is False     # 行内按钮同样绕不过
        gate.set()
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents(); time.sleep(0.01)
        assert group.busy is False
        assert tab.move("b2", -1) is True                     # 释放后恢复正常
        assert [i["id"] for i in rm_store.get_custom_items()] == ["b2", "a1"]
    finally:
        gate.set(); group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_editor_dialog_value_roundtrip(qapp):
    from modules.right_menu.custom import validate_item
    from modules.right_menu.widgets.editor_dialog import CustomItemDialog
    item = {"id": "abc123", "title": "用 VSCode 打开", "icon": "", "scope": "file",
            "ext_filter": [".py", ".md"], "hive": "hkcu", "extended": False,
            "position": "default", "action": {"kind": "program", "target": r"C:\vscode.exe",
            "args": '"%1"', "workdir": ""}, "children": []}
    dlg = CustomItemDialog(None, item=item)
    try:
        dom = dlg.value()
        assert dom["title"] == "用 VSCode 打开" and dom["ext_filter"] == [".py", ".md"]
        assert dom["action"]["target"].endswith("vscode.exe")
        out = validate_item(dom)
        assert out["ok"] and not out["errors"]
        # ── I4 契约钉死：id 保留 + 完整 DOM 键集（少一个键 validate/save 就静默丢字段）──
        assert dom["id"] == "abc123"
        assert set(dom) == DOM_KEYS
        assert set(dom["action"]) == {"kind", "target", "args", "workdir"}
        # 编辑态下改标题/目标，id 与其余字段仍原样（换了 id 就等于新建一条，旧投影成孤儿）
        dlg.title_edit.setText("改名了")
        assert dlg.value()["id"] == "abc123" and dlg.value()["title"] == "改名了"
        # 新建路径：id 由对话框层生成 = 8 位十六进制，且键集与编辑态完全一致
        fresh = CustomItemDialog(None)
        try:
            made = fresh.value()
            assert len(made["id"]) == 8 and int(made["id"], 16) >= 0
            assert set(made) == DOM_KEYS
            assert made["hive"] == "hkcu" and made["position"] == "default"
        finally:
            fresh.deleteLater(); qapp.processEvents()
    finally:
        dlg.deleteLater(); qapp.processEvents()


def test_custom_tab_move_persists(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu.widgets.page_tabs.custom_tab import CustomTab
    from modules.right_menu.workers import TaskGroup
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    a = {"id": "a1", "title": "A", "scope": "file", "ext_filter": [],
         "action": {"kind": "program", "target": "x", "args": "", "workdir": ""},
         "children": [], "icon": "", "hive": "hkcu", "extended": False, "position": "default"}
    b = dict(a, id="b2", title="B")
    rm_store.set_custom_items([a, b])
    group = TaskGroup()
    tab = CustomTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.move("b2", -1) is True                     # 上移
        ids = [i["id"] for i in rm_store.get_custom_items()]
        assert ids == ["b2", "a1"]
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_settings_tab_restore_all_roundtrip(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.page_tabs.settings_tab import SettingsTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\X", "", "X")
    rm_store.add_disabled("hkcu", r"Software\Classes\*\shell\X", None)
    r.set("hkcu", r"Software\Classes\*\shell\X", "LegacyDisable", "")
    group = TaskGroup()
    tab = SettingsTab(None, group, parent=None, page=None, backend=r)
    try:
        # 确认判定必须是**真值**判定：注入缝返回 None（`is False` 写法下会被当成同意）时
        # 一律当取消，且**不得**起任务、账本与注册表零改动——还原是本页唯一多数不可逆的动作。
        ledger_before = rm_store.load()["disabled"]
        assert tab.restore_all(confirm_fn=lambda *a, **k: None) is False
        assert not group.busy
        assert rm_store.load()["disabled"] == ledger_before
        assert r.get("hkcu", r"Software\Classes\*\shell\X", "LegacyDisable") == ""
        ok = tab.restore_all(confirm_fn=lambda *a, **k: True)
        deadline = __import__("time").time() + 5
        while group.busy and __import__("time").time() < deadline:
            qapp.processEvents()
        assert ok and r.get("hkcu", r"Software\Classes\*\shell\X", "LegacyDisable") is None
        assert rm_store.load()["disabled"] == []
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_settings_tab_yzmenu_apply_installs_checked_actions(qapp):
    """主开关开+全勾→install(ACTIONS)；去勾一个→install(ACTIONS 少一)；主开关关→uninstall。"""
    import time
    from modules.right_menu.widgets.page_tabs.settings_tab import SettingsTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    from modules.right_menu import yzmenu
    seen = []

    def fake_install(backend, actions, *, store_mod=None):
        seen.append(("install", list(actions)))
        return {"ok": True, "detail": "已安装"}

    def fake_uninstall(backend, *, store_mod=None):
        seen.append(("uninstall", []))
        return {"ok": True, "detail": "已卸载"}

    group = TaskGroup()
    tab = SettingsTab(None, group, parent=None, page=None, backend=FakeRegistry())
    orig_i, orig_u = yzmenu.install_yzmenu, yzmenu.uninstall_yzmenu
    yzmenu.install_yzmenu, yzmenu.uninstall_yzmenu = fake_install, fake_uninstall
    try:
        tab.check_yzmenu.setChecked(True)
        assert tab.apply_yzmenu() is True
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        assert seen == [("install", list(yzmenu.ACTIONS))]
        seen.clear()
        for box in tab.list_actions:
            if box.text() == yzmenu.ACTION_LABELS[yzmenu.ACTIONS[-1]]:
                box.setChecked(False)
        assert tab.apply_yzmenu() is True
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        assert seen == [("install", yzmenu.ACTIONS[:-1])]
        seen.clear()
        tab.check_yzmenu.setChecked(False)
        assert tab.apply_yzmenu() is True
        deadline = time.time() + 5
        while group.busy and time.time() < deadline:
            qapp.processEvents()
        assert seen == [("uninstall", [])]
    finally:
        yzmenu.install_yzmenu, yzmenu.uninstall_yzmenu = orig_i, orig_u
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_settings_tab_backups_table_lists_dir(qapp, tmp_path, monkeypatch):
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.page_tabs.settings_tab import SettingsTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / "20260101_000000_x.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(bk))
    group = TaskGroup()
    tab = SettingsTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        tab.refresh()
        assert tab.table_backups.rowCount() == 1
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


def test_settings_rows_pure_logic(tmp_path):
    """`settings_rows` 纯逻辑层（Qt-free，本测试不碰 QApplication）：空清单守卫 / 失败详情 /
    快照行组装与倒序。

    这一层是「到底要发哪份动作清单、快照表列哪几行、失败怎么呈现」的**唯一**决策点，而它在
    UI 层没有任何编译期信号：装出一个用户没要求的菜单、漏掉一份时间戳前缀的快照，都只有直接
    断言纯函数才拦得住。空清单那条尤其关键——「至少选择一个动作」是 yzmenu 侧的**合法拒绝
    路径**，在这里好心补一个动作就等于替用户做了决定。
    """
    from modules.right_menu import yzmenu
    from modules.right_menu.widgets.page_tabs import settings_rows as rows

    # ① 全不勾 → 空清单**原样**发出（不得好心补动作）。这是故意与「顺手兜个底」相反的设计。
    assert rows.wanted_actions(yzmenu.ACTIONS, [False] * len(yzmenu.ACTIONS)) == []
    # 部分勾选仍保持 ACTIONS 原序、不去重不补位。
    assert rows.wanted_actions(["a", "b", "c"], [True, False, True]) == ["a", "c"]
    # 控件数与 ACTIONS 不一致时按「没勾」处理，不 IndexError。
    assert rows.wanted_actions(["a", "b"], [True]) == ["a"]

    # ② 「至少选择一个动作」是返回值不是异常：非阻塞提示里必须带出 detail，且标题走失败分支。
    ok, title, body, hint = rows.result_view({"ok": False, "detail": "至少选择一个动作"})
    assert (ok, title) == (False, "操作失败")
    assert "至少选择一个动作" in body and "至少选择一个动作" in hint
    # 非 dict 的契约外返回值一律落 ok=False（不得因缺键而抛异常）。
    assert rows.result_view(None)[0] is False

    # ③ 快照行：只认 `.json`、时间戳前缀倒序（新→旧）、时间戳内含下划线不误切。
    names = ["20260101_000000_disable_hkcu.json", "20260102_010101_install_1.json",
             "readme.txt"]
    out = rows.backup_rows(names, str(tmp_path))
    assert len(out) == 2                                    # 非 json 文件不进表
    assert [r["time"] for r in out] == ["20260102_010101", "20260101_000000"]   # 倒序
    assert out[0]["reason"] == "install_1"      # `_1` 递增后缀归原因，不被切进时间
    assert out[1]["reason"] == "disable_hkcu"
    assert out[0]["path"] == str(tmp_path / "20260102_010101_install_1.json")
    # 不足两段的杂名整段当时间、原因空——不解析成乱码。
    assert rows.split_stem("junk.json") == ("junk", "")


def test_settings_tab_default_confirm_dialog_path(qapp, tmp_path, monkeypatch):
    """缺省确认路径（不注入 confirm_fn）：弹 RestoreDialog 预览，接受→起任务、拒绝→不起。

    上一轮只测了注入缝，等于把 `RestoreDialog.Accepted` ↔ `bool` 的换算完全漏在测试之外：
    那里把 `Rejected`（int 2）直接当 `False` 用，任何一次「返回值语义」的手滑都不可见。假对话框
    只记录构造并让 `exec()` 返回预设值——离屏环境里真弹模态框会挂起。
    """
    from core.qt_bootstrap import import_qt
    from modules.right_menu import store as rm_store
    from modules.right_menu.widgets.page_tabs import settings_tab as st
    from modules.right_menu.widgets.page_tabs.settings_tab import SettingsTab
    from modules.right_menu.workers import TaskGroup
    from modules.right_menu.registry_backend import FakeRegistry
    _, _QtCore, _QtGui, QtWidgets = import_qt()
    monkeypatch.setattr(rm_store, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(rm_store, "BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(rm_store, "TEMPLATES_DIR", str(tmp_path / "tp"))
    built = []

    class FakeDlg:
        code = QtWidgets.QDialog.Rejected

        def __init__(self, parent=None):
            built.append(parent)

        def exec(self):
            return self.code

        def deleteLater(self):
            pass

    monkeypatch.setattr(st, "RestoreDialog", FakeDlg)
    group = TaskGroup()
    tab = SettingsTab(None, group, parent=None, page=None, backend=FakeRegistry())
    try:
        assert tab.restore_all() is False            # Rejected → 不起任务
        assert len(built) == 1 and not group.busy
        FakeDlg.code = QtWidgets.QDialog.Accepted
        assert tab.restore_all() is True             # Accepted → 起线程
        deadline = __import__("time").time() + 5
        while group.busy and __import__("time").time() < deadline:
            qapp.processEvents()
        assert len(built) == 2
    finally:
        group.shutdown(); tab.deleteLater(); qapp.processEvents()


# ── 系统右键子菜单动作分发（Task 19）─────────────────────────────────
# 安全纪律：toggle_classic / restore_all 分支的运行期就是 Win32Backend（真注册表 +
# 可能触发 UAC 提权）。下列测试一律先把 Win32Backend 与 classic.*/store.restore_all
# 换成假对象再调用，绝不允许未 monkeypatch 就走真实注册表/UAC 路径。


def test_dispatch_menu_action_unknown_returns_false(qapp):
    from modules.right_menu.module import Module

    class _Ctx:
        config = None; host_window = None; app = qapp; registry = None; tray = None

    m = Module(_Ctx())
    assert m.dispatch_menu_action("nope") is False


def test_dispatch_open_manager(qapp, monkeypatch):
    import ui.module_pages as mp

    calls = []
    monkeypatch.setattr(mp, "open_module_page", lambda mod, *a, **k: calls.append(mod))
    from modules.right_menu.module import Module

    class _Ctx:
        config = None; host_window = None; app = qapp; registry = None; tray = None

    m = Module(_Ctx())
    assert m.dispatch_menu_action("open_manager") is True
    assert calls and calls[0] is m


def test_dispatch_toggle_classic_both_directions(monkeypatch):
    import modules.right_menu.registry_backend as rb_mod
    import modules.right_menu.classic as classic_mod
    from modules.right_menu.module import Module

    monkeypatch.setattr(rb_mod, "Win32Backend", lambda: rb_mod.FakeRegistry())
    state = {"v": "disabled"}
    calls = []
    monkeypatch.setattr(classic_mod, "get_classic_state", lambda be: state["v"])
    monkeypatch.setattr(classic_mod, "enable_classic",
                        lambda be: calls.append("enable") or {"ok": True})
    monkeypatch.setattr(classic_mod, "disable_classic",
                        lambda be: calls.append("disable") or {"ok": True})

    class _Ctx:
        config = None; host_window = None; app = None; registry = None; tray = None

    m = Module(_Ctx())

    assert m.dispatch_menu_action("toggle_classic") is True
    assert calls == ["enable"]                         # disabled → 设为经典
    state["v"] = "enabled"
    assert m.dispatch_menu_action("toggle_classic") is True
    assert calls == ["enable", "disable"]              # enabled → 切回新版
    state["v"] = "unknown"
    assert m.dispatch_menu_action("toggle_classic") is True
    assert calls == ["enable", "disable", "enable"]    # unknown 也按「设为经典」处理


def test_dispatch_show_window_and_restore_all(monkeypatch):
    import modules.right_menu.registry_backend as rb_mod
    import modules.right_menu.store as store_mod
    from modules.right_menu.module import Module

    calls = []

    class _Win:
        def showNormal(self): calls.append("showNormal")
        def raise_(self): calls.append("raise_")
        def activateWindow(self): calls.append("activateWindow")

    class _Host:
        window = _Win()

    class _Ctx:
        config = None; app = None; registry = None; tray = None
        host_window = _Host()

    m = Module(_Ctx())
    assert m.dispatch_menu_action("show_window") is True
    assert calls == ["showNormal", "raise_", "activateWindow"]

    class _Ctx2:
        config = None; app = None; registry = None; tray = None; host_window = None

    assert Module(_Ctx2()).dispatch_menu_action("show_window") is False

    seen = {}
    # 只验证传递，勿读真注册表
    monkeypatch.setattr(rb_mod, "Win32Backend", lambda: "BE")
    monkeypatch.setattr(store_mod, "restore_all",
                        lambda be: seen.update(be=be) or {"ok": True})
    assert m.dispatch_menu_action("restore_all") is True
    assert seen["be"] == "BE"
    monkeypatch.setattr(store_mod, "restore_all", lambda be: {"ok": False})
    assert m.dispatch_menu_action("restore_all") is False


def test_start_consumes_pending_menu_action(qapp):
    import time as _time
    from modules.right_menu.module import Module

    class _Ctx:
        config = None; host_window = None; app = qapp; registry = None; tray = None

    ctx = _Ctx()
    ctx.pending_menu_action = "open_manager"

    m = Module(ctx)
    seen = []
    m.dispatch_menu_action = lambda a: seen.append(a) or True
    try:
        m.start()
        assert ctx.pending_menu_action is None   # 立即清空，防重复消费
        deadline = _time.monotonic() + 2.0
        while not seen and _time.monotonic() < deadline:
            qapp.processEvents()
            _time.sleep(0.01)
        assert seen == ["open_manager"]
    finally:
        m.stop()
