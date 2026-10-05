"""right_menu 模块：Windows 右键菜单管理器（M1–M7）。

`modules/registry.py` 靠 `MODULE_INFO` + `Module` 两个名字自动发现模块，
**缺任何一个都会静默跳过整个模块**，因此这里导出它们并写进 `__all__`。

**必须惰性导出**：registry 的模块发现（`getattr(MODULE_INFO)` + `getattr(Module)`）
在早退路径（`--version` / `--help`，以及后续接入的提权作业通道 `--elevated-job`）
上先于 Qt 导入发生。若在包顶层 import，registry 的一次 `getattr` 就会把
`module.py` 拖进早退路径——而 widgets（首页卡/页面控件）import Qt，`module.py`
必须保持 Qt-free，widgets 的 import 只能留在 `create_home_widget`/
`create_page` 的函数体内。因此这里只用 PEP 562 `__getattr__` 做代理，
导入本身不碰任何子模块。

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
