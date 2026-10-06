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
