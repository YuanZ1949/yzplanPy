"""right_menu 注册表后端：Protocol + Win32Backend（真实）+ FakeRegistry（测试）。

Windows 右键项全在注册表里（`Software\\Classes\\*\\shell` 等），本模块是 right_menu
唯一的注册表 I/O 边界：操作层（scan/ops/shellnew/classic/custom/yzmenu）只认
`RegistryBackend` 这六个方法；测试注入 `FakeRegistry`（零真实注册表读写），提权通道
（elevate）在独立进程注入 `Win32Backend` 真写。

跨任务契约：
  * **Qt-free**：本文件是提权早退通道（`main.py --elevated-job`）在一切 Qt import
    之前要走的第一层代码，禁 import PySide6 / module.py。
  * **惰性 winreg**：`import winreg` 写在方法体内、模块顶层不持有引用；非 Windows 或
    测试注入 `sys.modules["winreg"] = None` 时抛 ImportError，由 `_open` 吞掉降级。
  * **永不抛异常**：键不存在/无权限/hive 未知/winreg 缺失一律 None / [] / 静默成功，
    调用方不必 try/except。代价：写失败（HKLM 未提权）也静默，需知成败者回读校验。
  * **大小写**：hive、键路径、值名都大小写不敏感（真实注册表如此）——账本条目与 scan
    输出用小写 "hkcu"、别处用大写 "HKCU"，须命中同一棵树；`list_*` 返回原样大小写。
  * `name=None` 指默认值（winreg 的 ""）；`set` 显式传 name（"" 即默认值）并自动创建
    缺失的中间层级；`delete` 只删值，删子树用 `delete_tree`。
"""
from typing import Protocol, runtime_checkable

__all__ = ["HKCU", "HKLM", "RegistryBackend", "Win32Backend", "FakeRegistry"]

HKCU = "HKCU"      # 仅支持这两个根（HKEY_CLASSES_ROOT 不在扫描范围内）
HKLM = "HKLM"


# ── 归一化助手（两后端共用）────────────────────────────────────────────
def _hive(hive):
    """hive 归一化：大小写/空白不敏感。"""
    return str(hive or "").strip().upper()


def _clean(path):
    """去首尾空白与首尾反斜杠，保留原始大小写（list_keys 要返回原样段名）。"""
    return str(path or "").strip().strip("\\")


def _norm(path):
    """键路径归一化（字典键用）：真实注册表键名大小写不敏感。"""
    return _clean(path).casefold()


def _name(name):
    """值名归一化：`None` 即默认值（winreg 的 `""`）。"""
    return "" if name is None else str(name)


def _text(value):
    """值统一文本化：bytes 解码（errors="replace"），None→""，其余 `str()`。"""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return "" if value is None else str(value)


# ── 协议 ──────────────────────────────────────────────────────────────
@runtime_checkable
class RegistryBackend(Protocol):
    """注册表访问协议（结构化子类型：两个实现都不必显式继承本类）。

    六个方法是所有操作层任务的契约：`get` 对不存在的键/值返回 None 而非抛；`set`
    显式传 name（`""` 即默认值）并自动创建缺失的中间层级；`delete` / `delete_tree`
    对不存在的键/值静默成功；`list_*` 返回原始大小写、键不存在返回 []。
    """

    def get(self, hive: str, path: str, name: str | None = None) -> str | None: ...
    def set(self, hive: str, path: str, name: str, value) -> None: ...
    def delete(self, hive: str, path: str, name: str | None = None) -> None: ...
    def delete_tree(self, hive: str, path: str) -> None: ...
    def list_keys(self, hive: str, path: str) -> list[str]: ...
    def list_values(self, hive: str, path: str) -> list[tuple[str, str]]: ...


# ── 真实后端 ──────────────────────────────────────────────────────────
class Win32Backend:
    """真实注册表后端（HKCU / HKLM）。任何失败都降级，绝不向上抛异常。"""

    @staticmethod
    def _root(winreg, hive):
        """hive → 根键常量；未知 hive 返回 None（调用方据此兜底）。"""
        return {"HKCU": winreg.HKEY_CURRENT_USER,
                "HKLM": winreg.HKEY_LOCAL_MACHINE}.get(_hive(hive))

    def _open(self, hive, path, access):
        """惰性导入 winreg + 映射根键 + 打开键，返回 `(winreg, key)`。

        `access`：`"read"`（OpenKeyEx/KEY_READ）、`"set"`（OpenKeyEx/KEY_SET_VALUE，
        删值用）、`"create"`（CreateKeyEx/KEY_SET_VALUE，自动建缺失层级）。任何一步
        失败都返回 `(None, None)`——「永不抛异常」集中在这里实现。
        """
        try:
            import winreg
        except ImportError:      # 非 Windows / 测试注入 sys.modules["winreg"]=None
            return None, None
        root = self._root(winreg, hive)
        if root is None:         # 未知 hive：不猜根键，直接兜底
            return None, None
        try:
            if access == "create":
                return winreg, winreg.CreateKeyEx(root, _clean(path), 0, winreg.KEY_SET_VALUE)
            mask = winreg.KEY_READ if access == "read" else winreg.KEY_SET_VALUE
            return winreg, winreg.OpenKeyEx(root, _clean(path), 0, mask)
        except (OSError, ValueError):
            return None, None

    def _call(self, hive, path, access, action, fallback):
        """在打开的键上执行 `action(winreg, key)`；任何失败返回 `fallback`。"""
        winreg, key = self._open(hive, path, access)
        if key is None:
            return fallback
        try:
            return action(winreg, key)
        except (OSError, ValueError):     # 含 FileNotFoundError / PermissionError
            return fallback
        finally:
            key.Close()

    def get(self, hive, path, name=None):
        return self._call(hive, path, "read",
                          lambda w, k: _text(w.QueryValueEx(k, _name(name))[0]), None)

    def set(self, hive, path, name, value):
        # 无权限（如 HKLM 未提权）等写入失败也静默，需要知成败的调用方回读校验
        self._call(hive, path, "create",
                   lambda w, k: w.SetValueEx(k, _name(name), 0, w.REG_SZ, _text(value)), None)

    def delete(self, hive, path, name=None):
        self._call(hive, path, "set", lambda w, k: w.DeleteValue(k, _name(name)), None)

    def delete_tree(self, hive, path):
        """删键及其全部后代（子键深度优先，父键保留其余子键）。

        stdlib winreg **没有** `DeleteTree`（那是 .NET / pywin32 的 API），故先收集
        直接子键、递归删除，再 `DeleteKeyEx` 自身；顺序反了会因「键仍有子键」失败。
        """
        subkey = _clean(path)
        for child in self._call(hive, path, "read",
                                lambda w, k: _enum(k, w.EnumKey), []):
            self.delete_tree(hive, f"{subkey}\\{child}" if subkey else child)
        try:
            import winreg
            root = self._root(winreg, hive)
        except ImportError:      # 非 Windows / winreg 缺失
            return
        if root is None:         # 未知 hive：无从删起
            return
        try:
            # access=0 与 _open 的默认视图一致，避免 WOW64 视图错位删错键
            winreg.DeleteKeyEx(root, subkey, 0)
        except (OSError, ValueError):
            return              # 键不存在 / 无权限：静默

    def list_keys(self, hive, path):
        return self._call(hive, path, "read", lambda w, k: sorted(_enum(k, w.EnumKey)), [])

    def list_values(self, hive, path):
        return self._call(hive, path, "read",
                          lambda w, k: [(str(n), _text(v)) for n, v, _t in _enum(k, w.EnumValue)],
                          [])


def _enum(key, enum):
    """枚举键下全部条目；枚举结束（ERROR_NO_MORE_ITEMS）即正常终止。"""
    items, index = [], 0
    while True:
        try:
            items.append(enum(key, index))
        except OSError:
            return items
        index += 1


# ── 测试后端 ──────────────────────────────────────────────────────────
class _Node:
    """内存树的一个键：`display` 是写入时的原始路径，`values` 是值表。"""

    __slots__ = ("display", "values")

    def __init__(self, display):
        self.display = display
        self.values: dict[str, tuple[str, str]] = {}   # 值名 casefold → (原名, 值)


class FakeRegistry:
    """内存注册表树，与 Win32Backend 行为对齐（测试唯一注入对象）。

    键路径与值名都大小写不敏感，`list_*` 返回原始大小写；`set` 自动创建中间层级；
    键/值不存在一律静默成功；未知 hive 视作独立命名空间（不抛）。
    """

    def __init__(self):
        self._nodes: dict[tuple[str, str], _Node] = {}   # (hive, 归一化路径) → 节点

    def get(self, hive, path, name=None):
        node = self._nodes.get((_hive(hive), _norm(path)))
        if node is None:
            return None
        entry = node.values.get(_name(name).casefold())
        return None if entry is None else entry[1]

    def set(self, hive, path, name, value):
        node = self._ensure(hive, _clean(path))
        if node is None:                 # 空路径：不建模 hive 根的值
            return
        node.values[_name(name).casefold()] = (_name(name), _text(value))

    def delete(self, hive, path, name=None):
        node = self._nodes.get((_hive(hive), _norm(path)))
        if node is not None:
            node.values.pop(_name(name).casefold(), None)

    def delete_tree(self, hive, path):
        hive_key, target = _hive(hive), _norm(path)
        for key in [k for k in self._nodes
                    if k[0] == hive_key and (not target or k[1] == target
                                            or k[1].startswith(target + "\\"))]:
            del self._nodes[key]

    def list_keys(self, hive, path):
        """直接子键名；`path` 空时列 hive 根下一层（与 Win32Backend 同义）。"""
        hive_key, target = _hive(hive), _norm(path)
        depth = len(target.split("\\")) if target else 0
        names = set()
        for (node_hive, node_path), node in self._nodes.items():
            rest = node_path[len(target) + 1:] if target else node_path  # 父路径之后的部分
            if node_hive != hive_key or not rest or "\\" in rest:
                continue           # 非本 hive / 非直接子键（更深一层）
            if target and not node_path.startswith(target + "\\"):
                continue
            names.add(node.display.split("\\")[depth])
        return sorted(names)

    def list_values(self, hive, path):
        node = self._nodes.get((_hive(hive), _norm(path)))
        return [] if node is None else list(node.values.values())

    def _ensure(self, hive, display):
        """返回该路径的节点，顺带创建缺失的中间层级（display 保留原大小写）。"""
        hive_key = _hive(hive)
        normalized = ""
        node = None
        for segment in display.split("\\") if display else []:
            folded = segment.casefold()
            normalized = f"{normalized}\\{folded}" if normalized else folded
            prefix = f"{node.display}\\{segment}" if node else segment
            node = self._nodes.get((hive_key, normalized))
            if node is None:
                node = self._nodes[(hive_key, normalized)] = _Node(prefix)
        return node