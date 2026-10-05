"""classic 经典右键菜单总开关：写 CLSID 默认值 + 重启资源管理器。

Windows 11 把新版右键菜单（可复制路径 / 打开终端那一套）做成 COM 组件，只有在该
COM 类的 `InprocServer32` 注册缺失时才回落到旧版 shell 菜单。业界的开关做法是往
`HKCU\\Software\\Classes\\CLSID\\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}`
的 `InprocServer32` 键写一个**空的默认值**（一个没有值的 COM 代理注册，使系统找不到
实现 → 用旧菜单）；还原则是删掉整棵 CLSID 子树。所以本模块只有两个写动作，且都落在
HKCU——用户自己的 hive，写入不需要提权。

为什么要有 `unknown` 三态而不是布尔：这个 CLSID 是微软文档化的 COM 注册位，别家软件
（压缩软件、git 客户端菜单壳等）可能已在同一位上注册了真正的实现。此时值非空或键存在
而没有默认值，UI 必须显示「状态未知」并**拒绝**改写，否则会把别人的 COM 注册抹掉。

跨任务契约：
  * **Qt-free**：只用 stdlib + `registry_backend` 的后端协议；本文件在
    `--elevated-job` 早退通道与纯逻辑测试里都可直接 import。
  * **永不抛**：explorer 重启是 `taskkill` + `start`，权限被杀软拦下 / 命令不存在都
    属常态，一律降级成 `{"ok": False, "detail": "请手动重启资源管理器"}`。
  * **依赖方向单向**：只依赖 `registry_backend`（更底层的 I/O 边界），不反向 import
    `ops` / `store` / `elevate`，也不在经典开关上记账本（它不是「右键项」，没有
    逐项的 original 值可备份）。

注意：`enable_classic` / `disable_classic` **不做写后回读**（与 `ops.apply_op` 不同）——
HKCU 写入几乎不会被拒，且回读只能证明「写落地」不能证明「系统已按经典菜单渲染」，
真正生效的判据是重启 explorer 后的 `get_classic_state`。需要确证写入的调用方自行回读。
"""
import subprocess

__all__ = [
    "CLASSIC_CLSID", "CLSID_KEY", "INPROC_KEY",
    "get_classic_state", "enable_classic", "disable_classic", "restart_explorer",
]

# 微软文档化的「新版右键菜单 COM 宿主」类 ID：它的 InprocServer32 有实现就用新版菜单，
# 没有（空注册）就回落到旧版 shell 菜单。
CLASSIC_CLSID = "{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
CLSID_KEY = rf"Software\Classes\CLSID\{CLASSIC_CLSID}"
INPROC_KEY = CLSID_KEY + r"\InprocServer32"

# `_list_keys` 返回的是子键的原始大小写，比较时统一 casefold（注册表键名不敏感）。
_INPROC_SUBKEY = "inprocserver32"


def get_classic_state(backend):
    """读当前状态：`"enabled"` / `"disabled"` / `"unknown"`。

    判定顺序（从最确定的信号往下）：
      1. `InprocServer32` 默认值为空串 → enabled（经典菜单已开）。
      2. 默认值非空 → unknown（这个 CLSID 被别的 COM 注册占着，改它会破坏对方）。
      3. 无默认值 → 看 `InprocServer32` 子键在不在：在但没默认值 → unknown（半残的
         注册，Windows 仍可能认它），不在 → disabled（键树压根没有 = 新版菜单）。
    """
    value = backend.get("hkcu", INPROC_KEY)
    if value is None:
        subs = backend.list_keys("hkcu", CLSID_KEY)
        if any(str(sub).casefold() == _INPROC_SUBKEY for sub in subs):
            return "unknown"
        return "disabled"
    return "enabled" if value == "" else "unknown"


def enable_classic(backend):
    """开启经典菜单：给 `InprocServer32` 写空默认值（`set` 会自建缺失的中间层级）。"""
    backend.set("hkcu", INPROC_KEY, "", "")
    return {"ok": True, "detail": "已切换到经典菜单（需重启资源管理器生效）"}


def disable_classic(backend):
    """还原新版菜单：删掉整棵 CLSID 子树（键不存在时后端静默成功，故永远 ok）。"""
    backend.delete_tree("hkcu", CLSID_KEY)
    return {"ok": True, "detail": "已恢复新版右键菜单（需重启资源管理器生效）"}


def restart_explorer(*, runner=None):
    """重启资源管理器使注册表改动生效。

    `runner` 是唯一注入点（默认 `subprocess.Popen`）：测试用它断言命令行，既不真的
    taskkill 用户的 shell，也不会因为本机没有 explorer 而失败。
    """
    cmd = ["cmd", "/c", "taskkill /f /im explorer.exe & start explorer.exe"]
    try:
        (runner or subprocess.Popen)(cmd)
    except Exception:       # 权限/被杀软/命令不存在：让用户手动重启，不向上抛
        return {"ok": False, "detail": "请手动重启资源管理器"}
    return {"ok": True, "detail": "已重启资源管理器"}