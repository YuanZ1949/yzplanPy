"""router_admin 模块：路由器状态监测与管理（telnet）。

`modules/registry.py` 靠 `MODULE_INFO` + `Module` 两个名字自动发现模块，
**缺任何一个都会静默跳过整个模块**，因此这里必须 re-export 且写进 `__all__`。

纯逻辑层（telnet / parsers / connection / store / services / wifi /
config_editor / backup）不 import Qt，可离线单测；UI 层集中在 `widgets/`。
"""
from .module import MODULE_INFO, Module

__all__ = ["MODULE_INFO", "Module"]
