"""yzmenu：把 YZplan 注册成一个自带子菜单的系统右键入口（全部落在 HKCU）。

形状是 Windows 经典的「静态子菜单」两段式：父键 `...\\shell\\YZplan` 只声明自己是菜单
（`SubCommands` 空串 = 我下面有子菜单），每个动作是 `父键\\shell\\<action>` 子键，其
**默认值**就是被点时执行的命令行，`MUIVerb` 是菜单上显示的汉字。

三个根都写：`*`（任何文件）、`Directory`（文件夹）、`Directory\\Background`（文件夹空白
处）。少写一个，用户就会在「文件右键有、文件夹空白处没有」这种地方报 bug；三处键形状
完全一致，同一段循环代码写完。

跨任务契约：
  * **Qt-free**：只用 stdlib + 本包 `store`；`--elevated-job` 早退通道可直接 import。
  * **零提权**：只写 HKCU，用户自己的 hive，不需要提权，也没有提权失败分支。
  * **依赖方向单向**：只依赖 `registry_backend` 的后端协议与 `store`，不反向 import
    `ops` / `elevate`。
  * **调用时读全局**：`PROJECT_DIR` 在函数体内 import，测试可 monkeypatch。
  * **校验先于写入**：动作名不在 `ACTIONS` 里、或清洗后清单为空（空壳菜单），就整条拒绝，
    账本与注册表都不碰一个字节。

`action_command` 的双模式 exe 解析镜像 `core/restart.py`（及 `elevate.build_launch_cmd`）：
frozen 用 `sys.executable`；开发优先 `PROJECT_DIR\\.venv\\Scripts\\pythonw.exe`（右键弹出的
黑窗对用户是打扰），没有 pythonw 才退回 `sys.executable`，非 frozen 一律追加 `main.py`。
`Icon` 取同一条基础命令的 exe 段，与动作命令共用 `_base_argv` → 换启动方式只改一处。
"""
import os
import subprocess
import sys

from . import store

__all__ = ["ROOTS", "ACTIONS", "ACTION_LABELS", "MENU_NAME", "menu_key",
           "action_command", "install_yzmenu", "uninstall_yzmenu", "get_yzmenu_state"]

_HIVE = "hkcu"
_CLASSES = r"Software\Classes"
MENU_NAME = "YZplan"

# 三个右键入口根：任意文件 / 文件夹 / 文件夹空白处。顺序只影响写入顺序。
ROOTS = ("*", "Directory", r"Directory\Background")

ACTIONS = ["open_manager", "toggle_classic", "show_window", "restore_all"]
ACTION_LABELS = {"open_manager": "打开管理器",
                 "toggle_classic": "切换经典右键菜单",
                 "show_window": "显示主窗口",
                 "restore_all": "还原全部已禁用的项"}

# 判「父键在不在」用的特征值名：这三个是本模块建键时必写的，命中任一即我们的键还在。
_PARENT_VALUES = ("MUIVerb", "SubCommands", "Position")
_BAD_ACTION = "动作清单里有未知动作"
_NO_ACTION = "至少选择一个动作"
_WRITE_FAILED = "写入未生效（可能被安全软件拦截）"


# ── 键路径 / 命令行 ────────────────────────────────────────────────────
def menu_key(root):
    """某个右键根下本菜单的父键路径。"""
    return rf"{_CLASSES}\{root}\shell\{MENU_NAME}"


def _action_key(root, action):
    """某个动作在某个根下的子键路径（默认值即命令行）。"""
    return menu_key(root) + rf"\shell\{action}"


def _base_argv():
    """双模式基础命令行（开发模式带 `main.py`）；`Icon` 取其 exe 段，保持单源。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    from core.constants import PROJECT_DIR        # 调用时读全局，便于 monkeypatch
    pythonw = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pythonw.exe")
    return [pythonw if os.path.exists(pythonw) else sys.executable,
            os.path.join(PROJECT_DIR, "main.py")]


def action_command(action):
    """完整命令行（单字符串）：双模式基础命令 + `--menu-action <动作>`。

    用 `list2cmdline` 拼：路径里有空格（`C:\\Program Files\\...`）也不会被 explorer
    拆成两段。这条命令直接当子键的默认值写。
    """
    return subprocess.list2cmdline(_base_argv() + ["--menu-action", str(action or "")])


def _icon():
    """菜单图标 = 基础命令的 exe 段（与动作命令同源）。"""
    return _base_argv()[0]


def _result(ok, detail):
    """统一返回形状（只有 ok/detail 两个键——调用方只认这两个）。"""
    return {"ok": bool(ok), "detail": str(detail)}


# ── 读状态 ────────────────────────────────────────────────────────────
def _installed(backend, key):
    """父键是否还在（本模块建的三个特征值命中任一即算在）。"""
    return any(backend.get(_HIVE, key, name) is not None for name in _PARENT_VALUES)


def get_yzmenu_state(backend):
    """当前状态：以 `*` 根为准的「装没装」+「挂了哪些已知动作」。

    只信 `*` 根：三个根由 install/uninstall 同一段代码同进同出，任何时刻三者一致，
    拿一个根判状态足够。动作名按 `ACTIONS` 顺序返回（注册表枚举是排过序的，直接用
    会把菜单顺序弄乱）；`list_keys` 返回原始大小写，比较统一 casefold；未知子键不认。
    """
    key = menu_key(ROOTS[0])
    if not _installed(backend, key):
        return {"installed": False, "actions": []}
    present = {str(name).casefold() for name in backend.list_keys(_HIVE, key + r"\shell")}
    return {"installed": True,
            "actions": [a for a in ACTIONS if a.casefold() in present]}


# ── 校验 / 写 / 删 ─────────────────────────────────────────────────────
def _validate(actions):
    """`(动作名列表, 错误文案)`：只判合法性（不改顺序、不去重）。

    与清洗分开是刻意的：本函数在**任何写入之前**跑，把未知动作整条拒掉，否则会把
    `--menu-action <未知>` 写进右键菜单、用户点了什么也不发生。标量入参当空清单。
    """
    try:
        raw = list(actions or [])
    except TypeError:                     # 非可迭代标量（如 int）当空，绝不抛
        raw = []
    names = [str(item or "").strip() for item in raw]
    for name in names:
        if name not in ACTION_LABELS:
            return [], f"{_BAD_ACTION}：{name or '（空）'}"
    if not names:                         # 空清单/None/标量一律落这里
        # 建出来的是一条 SubCommands 空壳菜单：右键能看见、点开什么都没有，还占着
        # 「已安装」的位置。比直接报错更难排查，所以在这里就拒掉。
        return [], _NO_ACTION
    return names, None


def _unique(names):
    """去重（保持调用方给的顺序）→ 动作清单最终形态。"""
    return list(dict.fromkeys(names))


def _purge(backend):
    """删掉三个根下的整棵 YZplan 子树（键不存在时后端静默成功，故永远幂等）。

    只清注册表、不碰账本：install 拿它做幂等前置清理时，账本在建键成功后才由
    `set_yzmenu(True, ...)` 一次写到位，避免中途出现「已安装 → 未安装」的闪烁。
    """
    for root in ROOTS:
        backend.delete_tree(_HIVE, menu_key(root))


def _write_root(backend, root, actions):
    """写一个根下的父键 + 各动作子键（键形状三处一致，循环里同一段代码）。"""
    key = menu_key(root)
    backend.set(_HIVE, key, "MUIVerb", MENU_NAME)
    backend.set(_HIVE, key, "Icon", _icon())
    backend.set(_HIVE, key, "SubCommands", "")     # 空串 = 我下面挂着子菜单
    backend.set(_HIVE, key, "Position", "Top")
    for action in actions:
        sub = _action_key(root, action)
        backend.set(_HIVE, sub, "", action_command(action))    # 默认值 = 命令行
        backend.set(_HIVE, sub, "MUIVerb", ACTION_LABELS[action])


def _write_confirmed(backend, actions):
    """建键后回读：父键在、每个动作子键的默认值非空，才算写落地。

    后端的 `set` 永不报错（无权限 / 被杀软拦都静默成功），所以「没抛异常」不等于
    「写进去了」；要知成败只能回读（与 `ops.apply_op` 同一判据）。
    """
    if not _installed(backend, menu_key(ROOTS[0])):
        return False
    return all(backend.get(_HIVE, _action_key(ROOTS[0], action))
               for action in actions)


def install_yzmenu(backend, actions, *, store_mod=None):
    """安装子菜单：动作清单 → 三个根的键 + 账本。

    清单为空（`[]` / `None` / 标量）或含未知动作一律拒（零副作用）：空清单建出来的是
    点开什么都没有的壳菜单。写入前先 `_purge` 清旧键：改动作清单时不会把上一次的残留
    动作子键留在菜单里（菜单是从子键枚举出来的，残留 = 多一行点不动的灰菜单）。
    """
    names, error = _validate(actions)
    if error is not None:                  # 校验在任何写入之前，失败即零副作用
        return _result(False, error)
    wanted = _unique(names)
    _purge(backend)
    for root in ROOTS:
        _write_root(backend, root, wanted)
    if not _write_confirmed(backend, wanted):        # 回读没过 → 账本一个字都不动
        return _result(False, _WRITE_FAILED)
    (store_mod or store).set_yzmenu(True, wanted)
    return _result(True, f"已安装「{MENU_NAME}」右键菜单（{len(wanted)} 个动作）")


def uninstall_yzmenu(backend, *, store_mod=None):
    """卸载子菜单：删三个根的键 + 账本归位（installed=False, actions=[]）。

    幂等：没装过也报成功（`delete_tree` 对不存在的键静默成功）。
    """
    _purge(backend)
    (store_mod or store).set_yzmenu(False, [])
    return _result(True, f"已卸载「{MENU_NAME}」右键菜单")
