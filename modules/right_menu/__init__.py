"""right_menu 模块：Windows 右键菜单管理器（M1–M7）。

`modules/registry.py` 靠 `MODULE_INFO` + `Module` 两个名字自动发现模块，
**缺任何一个都会静默跳过整个模块**，因此这里导出它们并写进 `__all__`。

**必须惰性导出**：应用有一条早退路径（`--version` / `--help` / 提权作业）在导入
任何 Qt 之前就要走完注册表发现；而 `module.py` 会 import Qt（首页卡定时器与页面
控件），若在包顶层 import，`import modules.right_menu` 就会把 Qt 拖进早退路径，
因此这里只用 PEP 562 `__getattr__` 做代理，导入本身不碰任何子模块。

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
