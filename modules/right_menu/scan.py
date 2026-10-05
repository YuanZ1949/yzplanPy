"""right_menu 四作用域右键项扫描：file / directory / background / drive。

Windows 的右键项全在注册表的 `shell` 键下（`Software\\Classes\\*\\shell` 等），
本模块只做**只读**枚举与元数据解析；禁用/删除/改名是 ops 的事，ShellNew 枚举在
shellnew 模块。

跨任务契约：
  * **Qt-free**：`--elevated-job` 早退通道可能在一切 Qt import 之前调用它，禁 import
    PySide6 / module.py。
  * **只认注入的 backend**：只调 registry_backend 六个方法，不自己碰 winreg；测试注入
    FakeRegistry 即可做到零真实注册表读写。未知 scope 返回 []，不抛。
  * **取值一律 str() 兜底**：后端已把值文本化，但历史/外部来源可能给出非字符串或
    None——任何 get 结果都先过 `_text`，绝不直接对原始结果调字符串方法（review 1）。
  * **hive 输出小写**（`hkcu`/`hklm`）：账本条目与下游任务按小写比对，hive 归一化由
    后端负责（`HKCU` ≡ `hkcu`），本模块只负责把来源 hive 固定成小写。

字段语义（MenuItem）：
  scope/display_name/command/icon  见下表；hive 小写；key_path 相对 hive 的完整路径；
  extended  仅「按住 Shift 才显示」；disabled 已带 LegacyDisable/ProgrammaticAccessOnly；
  builtin   无命令且无子项（系统内建伪项，不可删）；children 同构 dict 列表。

| 显示名（按优先级） | 命令 | 图标 |
|---|---|---|
| 子键 `MUIVerb`（`@` 开头的间接串原样显示并加「（间接字符串）」） | `command` 子键默认值 | `Icon` 值 |
| 子键默认值（空串视为无） | `DelegateExecute`（拼成 `(DelegateExecute) v`） | `key\\DefaultIcon` 默认值 |
| 键名（兜底，如 `open`） | 都无 → `None` + `builtin=True` | 都无 → `None` |

排序：禁用项排最后，两组内各按显示名 casefold 升序（不依赖 list_keys 的返回序）。
"""
__all__ = ["SCOPES", "SCOPE_ROOTS", "scan_scope"]

SCOPES = ("file", "directory", "background", "drive")

SCOPE_ROOTS = {
    "file": [r"Software\Classes\*", r"Software\Classes\AllFilesystemObjects"],
    "directory": [r"Software\Classes\Directory"],
    "background": [r"Software\Classes\Directory\Background"],
    "drive": [r"Software\Classes\Drive"],
}

_HIVES = ["hkcu", "hklm"]
_SKIP_KEYS = {"shellex"}                       # COM 扩展处理器，不是右键项
_DISABLE_VALUES = ("legacydisable", "programmaticaccessonly")   # 存在即已禁用（空串也算）
_INDIRECT = "（间接字符串）"                     # MUIVerb 间接串标注


# ── 取值兜底 ──────────────────────────────────────────────────────────
def _text(value):
    """值统一文本化：bytes 解码（errors="replace"），None→""，其余 `str()`。"""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return "" if value is None else str(value)


def _value(backend, hive, path, name=None):
    """读一个值并文本化；键/值不存在返回 ""（空串与 None 同义：都是「无值」）。"""
    return _text(backend.get(hive, path, name))


def _exists(backend, hive, path, name):
    """值是否存在——`Extended`/`LegacyDisable` 等标志值写的是空串，存在即 True。"""
    return backend.get(hive, path, name) is not None


# ── 元数据解析 ────────────────────────────────────────────────────────
def _display_name(backend, hive, key, keyname):
    """MUIVerb（间接串加标注）> 默认值 > 键名。空串一律视为无，逐级回退。"""
    mui = _value(backend, hive, key, "MUIVerb")
    if mui:
        return mui + _INDIRECT if mui.startswith("@") else mui
    return _value(backend, hive, key) or keyname


def _command(backend, hive, key):
    """`key\\command` 默认值 > `DelegateExecute`（标注）> None（系统内建伪项）。"""
    command = _value(backend, hive, key + r"\command")
    if command:
        return command
    delegate = _value(backend, hive, key, "DelegateExecute")
    return f"(DelegateExecute) {delegate}" if delegate else None


def _icon(backend, hive, key):
    """`Icon` 值 > `key\\DefaultIcon` 默认值 > None（间接串原样展示，不解析资源）。"""
    return _value(backend, hive, key, "Icon") or _value(backend, hive, key + r"\DefaultIcon") or None


def _disabled(backend, hive, key):
    """已带禁用值（LegacyDisable / ProgrammaticAccessOnly，含空串）即 True。"""
    return any(_exists(backend, hive, key, name) for name in _DISABLE_VALUES)


# ── 枚举 ──────────────────────────────────────────────────────────────
def _build(backend, hive, scope, key):
    """一个 shell 子键 → MenuItem dict（子项同构递归）。"""
    children = _submenu(backend, hive, scope, key)
    command = _command(backend, hive, key)
    return {"scope": scope, "hive": hive, "key_path": key,
            "display_name": _display_name(backend, hive, key, key.rsplit("\\", 1)[-1]),
            "command": command, "icon": _icon(backend, hive, key),
            "extended": _exists(backend, hive, key, "Extended"),
            "disabled": _disabled(backend, hive, key),
            "children": children, "builtin": command is None and not children}


def _collect(backend, hive, scope, shell_dir):
    """一个 `\\shell` 目录的直接子键 → MenuItem 列表（跳过 shellex，不排序）。"""
    return [_build(backend, hive, scope, f"{shell_dir}\\{name}")
            for name in backend.list_keys(hive, shell_dir)
            if name.casefold() not in _SKIP_KEYS]


def _order(items, disabled_last):
    """按显示名 casefold 升序；`disabled_last` 为真时禁用项整体排到末尾。"""
    def by_name(item):
        return item["display_name"].casefold()

    if not disabled_last:
        return sorted(items, key=by_name)
    return (sorted([i for i in items if not i["disabled"]], key=by_name)
            + sorted([i for i in items if i["disabled"]], key=by_name))


def _submenu(backend, hive, scope, key):
    """级联子菜单：有 `SubCommands` 值或存在 `shell` 子键时才递归（避免多一次枚举）。"""
    shell_dir = key + r"\shell"
    if not (_exists(backend, hive, key, "SubCommands") or backend.list_keys(hive, shell_dir)):
        return []
    return _order(_collect(backend, hive, scope, shell_dir), False)


def scan_scope(backend, scope, *, include_hklm=True):
    """扫一个作用域，返回 MenuItem 列表；未知 scope 返回 []。

    遍历 SCOPE_ROOTS[scope] × hive（`include_hklm=False` 时只扫 HKCU——未提权进程读
    HKLM 看不到全部项），最后禁用项排后、组内按显示名排序。
    """
    roots = SCOPE_ROOTS.get(scope)
    if not roots:
        return []                  # 未知作用域：无可扫路径，绝不抛
    hives = _HIVES[:1] if not include_hklm else _HIVES
    items = [item for hive in hives for root in roots
             for item in _collect(backend, hive, scope, root + r"\shell")]
    return _order(items, True)