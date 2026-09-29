"""proxy_ctrl 模块：本机代理控制 + 局域网代理扫描。

移植自 `Desktop/toggle_proxy`（全能代理管理器 v3.2，伊涅芙）。与原版的**两处
关键差异**：

1. **环境变量写 HKCU\\Environment 并广播 WM_SETTINGCHANGE**（见 `envstore`）。
   原版 PowerShell 只做 `$env:x = $url`，仅影响当前进程，退出即失效；本模块
   写用户级持久化，新开的终端/IDE 才真正拿到代理。
2. **扫描/测速用纯 Python 线程池**（见 `scanner` / `speedtest`），不再 fork
   PowerShell runspace；防误报铁律「generate_204 必须精确返回 204」原样保留。

`modules/registry.py` 靠 `MODULE_INFO` + `Module` 两个名字自动发现模块，
**缺任何一个都会静默跳过整个模块**，因此这里必须 re-export 且写进 `__all__`。

纯逻辑层（envstore / targets / store / scanner / speedtest）不 import Qt，可离线
单测；UI 层集中在 `widgets/`，线程封装在 `workers.py`。
"""
from .module import MODULE_INFO, Module

__all__ = ["MODULE_INFO", "Module"]
