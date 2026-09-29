"""router_admin/store：连接参数与 UI 偏好持久化，口令用 DPAPI 加密。

DPAPI（CryptProtectData，CRYPTPROTECT_UI_FORBIDDEN）按当前 Windows 用户加密，
换机器 / 换用户解密必然失败 —— 此时返回 None 让 UI 要求重填，**不降级明文**。
"""
import base64
import json
import os

from core.constants import DATA_DIR

from .connection import (DEFAULT_CONNECT_TIMEOUT, DEFAULT_HOST, DEFAULT_INTERVAL,
                         DEFAULT_PORT, DEFAULT_READ_TIMEOUT, DEFAULT_USER,
                         MAX_INTERVAL, MIN_INTERVAL)

SETTINGS_PATH = os.path.join(DATA_DIR, "router_admin", "settings.json")

# DPAPI 标志：禁止弹 UI（无头 / 服务环境必须用）
CRYPTPROTECT_UI_FORBIDDEN = 0x01

_DEFAULTS = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    "user": DEFAULT_USER,
    "password_blob": "",
    "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "auto_refresh": False,
    "interval": DEFAULT_INTERVAL,
    "lan_iface": "br-lan",
    "wan_iface": "pppoe-wan",
}


def dpapi_protect(plain):
    """DPAPI 加密，返回 base64 串。不可用时抛异常。"""
    import win32crypt
    data = win32crypt.CryptProtectData(
        (plain or "").encode("utf-8"), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN)
    return base64.b64encode(data).decode("ascii")


def dpapi_unprotect(blob):
    """DPAPI 解密，失败返回 None（不抛异常）。"""
    if not blob:
        return None
    try:
        import win32crypt
        raw = base64.b64decode(blob)
        plain = win32crypt.CryptUnprotectData(
            raw, None, None, None, CRYPTPROTECT_UI_FORBIDDEN)[1]
    except Exception:
        return None
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return None


def dpapi_available():
    """当前环境是否可用 DPAPI。"""
    try:
        import win32crypt  # noqa: F401
    except Exception:
        return False
    return True


def _coerce(settings):
    """把读回的 dict 规整成完整设置（未知键丢弃、类型兜底）。"""
    out = dict(_DEFAULTS)
    data = settings or {}
    for key in _DEFAULTS:
        if key in data:
            out[key] = data[key]
    try:
        out["port"] = int(out["port"])
    except (TypeError, ValueError):
        out["port"] = DEFAULT_PORT
    for key in ("connect_timeout", "read_timeout"):
        try:
            out[key] = float(out[key])
        except (TypeError, ValueError):
            out[key] = _DEFAULTS[key]
    try:
        out["interval"] = int(out["interval"])
    except (TypeError, ValueError):
        out["interval"] = DEFAULT_INTERVAL
    out["interval"] = max(MIN_INTERVAL, min(MAX_INTERVAL, out["interval"]))
    out["auto_refresh"] = bool(out["auto_refresh"])
    for key in ("host", "user", "lan_iface", "wan_iface"):
        out[key] = str(out[key] or _DEFAULTS[key])
    out["password_blob"] = str(out["password_blob"] or "")
    return out


def load():
    """读设置；文件缺失/损坏返回默认值。**不含明文口令**，口令在 password 键。"""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raw = None
    settings = _coerce(raw if isinstance(raw, dict) else None)
    settings["password"] = dpapi_unprotect(settings["password_blob"])
    return settings


def save(settings):
    """写设置。返回 True/False。password 键会被加密进 password_blob。"""
    data = _coerce(settings)
    plain = settings.get("password")
    if plain:
        try:
            data["password_blob"] = dpapi_protect(plain)
        except Exception:
            return False
    data.pop("password", None)
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except (OSError, ValueError):
        return False
    return True


def set_password(plain):
    """单独更新口令（设置面板用）。"""
    settings = load()
    settings["password"] = plain
    return save(settings)


def password_configured():
    """是否已存有可解密的口令。"""
    return bool(load().get("password"))


def data_dir():
    """数据目录（供「打开目录」）。"""
    return os.path.dirname(SETTINGS_PATH) or DATA_DIR
