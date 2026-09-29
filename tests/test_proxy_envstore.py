"""proxy_ctrl/envstore 单测：注册表后端 + 广播 + 本进程同步。

不触碰真实注册表：RegistryBackend 用 fake，WinRegistryBackend 用 monkeypatch
替换 winreg 调用。写 os.environ 的用例用 _restore_environ fixture 兜底还原。
"""
import os

import pytest

from modules.proxy_ctrl import envstore


class FakeBackend(envstore.RegistryBackend):
    """内存后端：记录调用，delete 不存在的值静默成功。"""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.calls = []

    def get(self, name):
        self.calls.append(("get", name))
        return self.data.get(name)

    def set(self, name, value):
        self.calls.append(("set", name, value))
        self.data[name] = str(value)

    def delete(self, name):
        self.calls.append(("delete", name))
        self.data.pop(name, None)


@pytest.fixture
def _restore_environ():
    """快照并还原本测试触碰的环境变量，避免污染后续用例。"""
    touched = ("http_proxy", "https_proxy", "socks_proxy", "YPROXY_TEST",
               "PROXY_TEST", "wget_proxy")
    saved = {k: os.environ.get(k) for k in touched}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def _fake_broadcast(monkeypatch):
    """拦截广播，断言是否被调用。"""
    calls = []
    monkeypatch.setattr(envstore, "_broadcast_impl",
                        lambda timeout_ms: calls.append(timeout_ms) or True)
    return calls


# ── read_env ──────────────────────────────────────────────────────────

def test_read_env_returns_none_when_absent():
    assert envstore.read_env(FakeBackend(), "http_proxy") is None


def test_read_env_returns_none_for_empty_string():
    assert envstore.read_env(FakeBackend({"http_proxy": ""}), "http_proxy") is None


def test_read_env_strips_whitespace():
    backend = FakeBackend({"http_proxy": "  http://127.0.0.1:7890  "})
    assert envstore.read_env(backend, "http_proxy") == "http://127.0.0.1:7890"


def test_read_env_swallows_backend_exception():
    class Broken(FakeBackend):
        def get(self, name):
            raise OSError("denied")

    assert envstore.read_env(Broken(), "http_proxy") is None


# ── write_env ─────────────────────────────────────────────────────────

def test_write_env_sets_backend_value(_restore_environ, _fake_broadcast):
    backend = FakeBackend()
    envstore.write_env(backend, "http_proxy", "http://127.0.0.1:7890")
    assert backend.data["http_proxy"] == "http://127.0.0.1:7890"


def test_write_env_syncs_current_process_env(_restore_environ, _fake_broadcast):
    envstore.write_env(FakeBackend(), "YPROXY_TEST", "http://127.0.0.1:7890")
    assert os.environ["YPROXY_TEST"] == "http://127.0.0.1:7890"


def test_write_env_triggers_broadcast(_restore_environ, _fake_broadcast):
    envstore.write_env(FakeBackend(), "PROXY_TEST", "http://127.0.0.1:1080")
    assert _fake_broadcast == [5000]


def test_write_env_honours_custom_timeout(_restore_environ, _fake_broadcast):
    envstore.write_env(FakeBackend(), "PROXY_TEST", "x", timeout_ms=1234)
    assert _fake_broadcast == [1234]


# ── unset_env ─────────────────────────────────────────────────────────

def test_unset_env_removes_backend_value(_restore_environ, _fake_broadcast):
    backend = FakeBackend({"http_proxy": "http://127.0.0.1:7890"})
    envstore.unset_env(backend, "http_proxy")
    assert "http_proxy" not in backend.data


def test_unset_env_silent_when_absent(_restore_environ, _fake_broadcast):
    backend = FakeBackend()
    envstore.unset_env(backend, "http_proxy")  # 不得抛异常
    assert backend.data == {}


def test_unset_env_pops_current_process_env(_restore_environ, _fake_broadcast):
    os.environ["YPROXY_TEST"] = "http://127.0.0.1:7890"
    envstore.unset_env(FakeBackend(), "YPROXY_TEST")
    assert "YPROXY_TEST" not in os.environ


def test_unset_env_triggers_broadcast(_restore_environ, _fake_broadcast):
    envstore.unset_env(FakeBackend(), "wget_proxy")
    assert _fake_broadcast == [5000]


# ── broadcast_environment_change ──────────────────────────────────────

def test_broadcast_returns_true_when_impl_succeeds(monkeypatch):
    monkeypatch.setattr(envstore, "_broadcast_impl", lambda timeout_ms: True)
    assert envstore.broadcast_environment_change() is True


def test_broadcast_returns_false_when_impl_fails(monkeypatch):
    monkeypatch.setattr(envstore, "_broadcast_impl", lambda timeout_ms: False)
    assert envstore.broadcast_environment_change() is False


def test_broadcast_swallows_exception(monkeypatch):
    def _boom(timeout_ms):
        raise OSError("no window station")

    monkeypatch.setattr(envstore, "_broadcast_impl", _boom)
    assert envstore.broadcast_environment_change() is False


# ── WinRegistryBackend ────────────────────────────────────────────────

class _FakeKey:
    def __init__(self, data, writable=True):
        self._data = data
        self._writable = writable
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True
        return False


class _FakeWinreg:
    """最小 winreg 替身，覆盖 OpenKey/CreateKeyEx/QueryValueEx/SetValueEx/DeleteValue。"""

    HKEY_CURRENT_USER = object()
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self, data=None, fail_open=False):
        self.data = dict(data or {})
        self.fail_open = fail_open
        self.written = []
        self.deleted = []

    def OpenKey(self, root, subkey, _reserved, access):
        if self.fail_open:
            raise OSError(2, "no such key")
        return _FakeKey(self.data)

    def CreateKeyEx(self, root, subkey, _reserved, access):
        return _FakeKey(self.data)

    def QueryValueEx(self, key, name):
        if name not in key._data:
            raise FileNotFoundError(name)
        return key._data[name], 1

    def SetValueEx(self, key, name, _res, _kind, value):
        self.written.append((name, value))
        key._data[name] = value

    def DeleteValue(self, key, name):
        if name not in key._data:
            raise FileNotFoundError(name)
        self.deleted.append(name)
        del key._data[name]


def test_win_backend_get_returns_none_on_oserror():
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = _FakeWinreg(fail_open=True)
    assert backend.get("http_proxy") is None


def test_win_backend_get_returns_value():
    winreg = _FakeWinreg({"http_proxy": "http://127.0.0.1:7890"})
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = winreg
    assert backend.get("http_proxy") == "http://127.0.0.1:7890"


def test_win_backend_get_returns_none_when_key_absent():
    winreg = _FakeWinreg({})
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = winreg
    assert backend.get("http_proxy") is None


def test_win_backend_set_writes_reg_sz():
    winreg = _FakeWinreg({})
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = winreg
    backend.set("http_proxy", "http://127.0.0.1:7890")
    assert winreg.written == [("http_proxy", "http://127.0.0.1:7890")]


def test_win_backend_delete_swallows_missing_value():
    winreg = _FakeWinreg({})
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = winreg
    backend.delete("http_proxy")  # 不得抛异常
    assert winreg.deleted == []


def test_win_backend_delete_removes_existing_value():
    winreg = _FakeWinreg({"http_proxy": "x"})
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = winreg
    backend.delete("http_proxy")
    assert winreg.deleted == ["http_proxy"]


def test_win_backend_get_returns_none_without_winreg():
    backend = envstore.WinRegistryBackend.__new__(envstore.WinRegistryBackend)
    backend._subkey = "Environment"
    backend._root = object()
    backend._winreg = None
    assert backend.get("http_proxy") is None
