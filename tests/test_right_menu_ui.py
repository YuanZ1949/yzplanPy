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
