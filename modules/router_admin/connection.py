"""router_admin/connection：连接参数与校验。

口令不落明文：store 用 DPAPI 加密，本模块只负责参数合法性与默认值。
"""
DEFAULT_HOST = "192.168.2.1"
DEFAULT_PORT = 23
DEFAULT_USER = "root"
DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_READ_TIMEOUT = 12.0
MIN_INTERVAL = 3
MAX_INTERVAL = 30
DEFAULT_INTERVAL = 5

#: 允许修改的 /etc/config 白名单（防止误改系统关键配置）
CONFIG_WHITELIST = (
    "network",
    "dhcp",
    "firewall",
    "wireless",
    "system",
    "dnsmasq",
)


class ConnectionError_(ValueError):
    """连接参数非法。命名为带下划线以免与内置 ConnectionError 冲突。"""


def validate_host(host):
    """校验主机名 / IP。非法抛 ConnectionError_。"""
    text = (host or "").strip()
    if not text:
        raise ConnectionError_("主机地址不能为空")
    if len(text) > 253:
        raise ConnectionError_("主机地址过长")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789.-_:[]")
    if not set(text) <= allowed:
        raise ConnectionError_(f"主机地址含非法字符：{text}")
    return text


def validate_port(port):
    """校验端口。非法抛 ConnectionError_。"""
    try:
        value = int(port)
    except (TypeError, ValueError):
        raise ConnectionError_(f"端口必须是数字：{port!r}")
    if not 1 <= value <= 65535:
        raise ConnectionError_(f"端口超出范围 1-65535：{value}")
    return value


def validate_timeout(value, name):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ConnectionError_(f"{name} 必须是数字：{value!r}")
    if not 0.5 <= seconds <= 120.0:
        raise ConnectionError_(f"{name} 超出范围 0.5-120 秒：{seconds}")
    return seconds


def validate_interval(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        raise ConnectionError_(f"刷新间隔必须是整数：{value!r}")
    return max(MIN_INTERVAL, min(MAX_INTERVAL, seconds))


def is_allowed_config(section):
    """section 名是否在 /etc/config 白名单内。"""
    return (section or "") in CONFIG_WHITELIST


class ConnectionParams:
    """一次连接所需的全部参数。"""

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 user=DEFAULT_USER, password="",
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 read_timeout=DEFAULT_READ_TIMEOUT):
        self.host = host
        self.port = port
        self.user = user
        self.password = password or ""
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout

    def validate(self):
        """校验全部参数；非法抛 ConnectionError_。返回 (host, port, user)。"""
        host = validate_host(self.host)
        port = validate_port(self.port)
        user = (self.user or "").strip()
        if not user:
            raise ConnectionError_("用户名不能为空")
        if any(ch in user for ch in " \t\r\n;|&`$"):
            raise ConnectionError_("用户名含非法字符")
        self.connect_timeout = validate_timeout(self.connect_timeout, "连接超时")
        self.read_timeout = validate_timeout(self.read_timeout, "读取超时")
        return host, port, user

    @classmethod
    def from_settings(cls, settings):
        """从 store 读出的 dict 构造（缺字段回落默认值）。"""
        data = settings or {}
        return cls(
            host=data.get("host") or DEFAULT_HOST,
            port=data.get("port") or DEFAULT_PORT,
            user=data.get("user") or DEFAULT_USER,
            password=data.get("password") or "",
            connect_timeout=data.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT),
            read_timeout=data.get("read_timeout", DEFAULT_READ_TIMEOUT),
        )

    def __repr__(self):  # pragma: no cover - 调试用，绝不打印口令
        return (f"ConnectionParams(host={self.host!r}, port={self.port!r}, "
                f"user={self.user!r}, password='***')")


def format_bytes(count):
    """把字节数格式化为易读字符串。"""
    try:
        value = float(count)
    except (TypeError, ValueError):
        return "-"
    if value < 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"
