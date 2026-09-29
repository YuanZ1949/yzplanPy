"""proxy_ctrl：Windows 用户环境变量读写 + WM_SETTINGCHANGE 广播。

原版 toggle_proxy（config.ps1 / config.sh）只做 `export` / `$env:x = $url`，
在 Windows 上仅影响当前进程，退出即失效。本模块改为写 `HKCU\\Environment`
并广播环境变更，使新开的终端/IDE 真正拿到代理。

Winreg 调用被包在 RegistryBackend 协议后面，测试注入 fake，不触碰真实注册表。
"""
import os

_IS_WINDOWS = os.name == "nt"

#: 广播用常量（Win32 API 固定值）
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
ENVIRONMENT_KEY = "Environment"


class RegistryBackend:
    """HKCU\\Environment 的最小访问协议。测试用 fake 实现同一接口。"""

    def get(self, name):
        """读值；不存在返回 None。"""
        raise NotImplementedError

    def set(self, name, value):
        """写 REG_SZ 值。"""
        raise NotImplementedError

    def delete(self, name):
        """删值；不存在须静默成功。"""
        raise NotImplementedError


def _import_winreg():
    if not _IS_WINDOWS:
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows 平台
        return None
    return winreg


class WinRegistryBackend(RegistryBackend):
    """真实注册表后端：HKCU\\Environment。"""

    def __init__(self, subkey=ENVIRONMENT_KEY, root=None):
        self._subkey = subkey
        self._winreg = _import_winreg()
        if root is None:
            if self._winreg is None:
                raise RuntimeError("当前平台不支持 Windows 注册表")
            root = self._winreg.HKEY_CURRENT_USER
        self._root = root

    def get(self, name):
        winreg = self._winreg
        if winreg is None:
            return None
        try:
            with winreg.OpenKey(self._root, self._subkey, 0,
                               winreg.KEY_QUERY_VALUE) as key:
                value, _kind = winreg.QueryValueEx(key, name)
        except OSError:
            return None
        return None if value is None else str(value)

    def set(self, name, value):
        winreg = self._winreg
        if winreg is None:
            raise RuntimeError("当前平台不支持 Windows 注册表")
        with winreg.CreateKeyEx(self._root, self._subkey, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

    def delete(self, name):
        winreg = self._winreg
        if winreg is None:
            return
        try:
            with winreg.OpenKey(self._root, self._subkey, 0,
                               winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except OSError:
            # 值不存在（FileNotFoundError）或权限不足：清除语义下前者必须静默
            return


def _broadcast_impl(timeout_ms):
    """真实广播：SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, ...)。"""
    if not _IS_WINDOWS:
        return False
    import ctypes
    result = ctypes.c_ulong()
    ok = ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST, WM_SETTINGCHANGE, 0,
        ctypes.c_wchar_p(ENVIRONMENT_KEY),
        SMTO_ABORTIFHUNG, int(timeout_ms), ctypes.byref(result))
    return bool(ok)


def broadcast_environment_change(timeout_ms=5000):
    """通知 Explorer/新进程环境已变。返回 True 表示广播已发出。"""
    try:
        return bool(_broadcast_impl(timeout_ms))
    except Exception:
        return False


def read_env(backend, name):
    """读用户环境变量；不存在或空串返回 None。"""
    try:
        value = backend.get(name)
    except Exception:
        return None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def write_env(backend, name, value, *, timeout_ms=5000):
    """写用户环境变量 + 同步本进程 + 广播。

    同步 os.environ 是为了让**当前 YZplan 进程**立即生效（已启动的子进程
    仍会继承旧值，需重启终端，这是 Windows 的固有语义）。
    """
    backend.set(name, str(value))
    os.environ[name] = str(value)
    broadcast_environment_change(timeout_ms)
    return value


def unset_env(backend, name, *, timeout_ms=5000):
    """删用户环境变量；不存在时静默成功。"""
    backend.delete(name)
    os.environ.pop(name, None)
    broadcast_environment_change(timeout_ms)
