"""right_menu 模块：Windows 右键菜单管理器（M1–M7）。

`modules/registry.py` 靠 `MODULE_INFO` + `Module` 两个名字自动发现模块，
**缺任何一个都会静默跳过整个模块**，因此这里导出它们并写进 `__all__`。

**必须惰性导出**：registry 的模块发现（`getattr(MODULE_INFO)` + `getattr(Module)`）
必须能在任何 Qt 导入之前完成——本应用预留的 `--elevated-job` 提权作业通道
（后续接入）将在一切 Qt import 之前走模块发现。这带来两条 Qt 自由保证：

  a) 后续任务的纯 Python 操作层/提权层（如 `modules/right_menu/elevate.py`）只需
     import 自己的子模块，而子模块导入必然先执行本 `__init__.py`——它不 import
     任何子模块，因此这类路径不触发 `module.py`；
  b) `module.py` 自身保持 Qt-free，于是即使 registry 的 `getattr` 按 PEP 562
     触发代理、进而加载 `module.py`，也拉不进 Qt。

换言之，惰性代理并不能阻止 `getattr` 加载 `module.py`（代理在首次取值时必然加载），
它保证的是 (a) 这条路径：只有 `module.py` 真的需要取值时才加载它。
widgets（首页卡/页面控件）import Qt，它们的 import 必须留在
`create_home_widget`/`create_page` 的函数体内，绝不放模块顶层。

纯逻辑层（registry_backend / store / scan / ops / shellnew / classic / custom /
yzmenu / elevate）不 import Qt，可离线单测；UI 层集中在 `widgets/`。
"""

__all__ = ["MODULE_INFO", "Module"]


def __getattr__(name):
    """PEP 562 惰性代理：首次取值时才 import .module，避免包导入引入 Qt。"""
    if name == "MODULE_INFO":
        from .module import MODULE_INFO

        return MODULE_INFO
    if name == "Module":
        from .module import Module

        return Module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
