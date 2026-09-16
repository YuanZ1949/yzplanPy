"""sys_info 模块：读取电脑配置信息。"""
import datetime
import platform
import re
import socket

from .base import ModuleBase


def collect_info(config=None):
    import psutil

    info = {}
    info["主机名"] = platform.node()
    info["系统"] = f"{platform.system()} {platform.release()}"
    info["版本"] = platform.version()
    info["机器"] = platform.machine()
    info["处理器"] = platform.processor() or _cpu_brand()
    info["物理核心"] = psutil.cpu_count(logical=False) or "未知"
    info["逻辑核心"] = psutil.cpu_count(logical=True) or "未知"
    vm = psutil.virtual_memory()
    info["内存总量"] = _fmt(vm.total)
    info["内存使用"] = f"{_fmt(vm.used)} / {_fmt(vm.total)} ({vm.percent}%)"
    info["GPU"] = _gpu_names() or "未知"
    info["系统盘"] = _disk_summary()
    # ── 扩展字段（追加在末尾）──────────────────────────────
    info["Python版本"] = platform.python_version()
    info["PySide6版本"] = _pyside6_version()
    info["qfluentwidgets版本"] = _qfw_version()
    info["网络适配器"] = _net_addrs()
    info["系统启动时间"] = _boot_time()
    info["磁盘IO"] = _disk_io()
    # ── 运行配置（追加在末尾）──────────────────────────────
    from core.autostart import autostart_enabled
    info["开机自启"] = "已启用" if autostart_enabled() else "未启用"
    info["主题"] = _resolve_theme(config) if config else "—"
    w = config.get("window.width") if config else None
    if w is None and config:
        w = config.get("ui.width")  # 兼容旧键（既有用户数据）
    h = config.get("window.height") if config else None
    if h is None and config:
        h = config.get("ui.height")  # 兼容旧键（既有用户数据）
    info["窗口尺寸"] = f"{w}×{h}" if w is not None and h is not None else "—"
    info["截图热键"] = "已启用" if config and config.module_setting("screenshot", "hotkey_enabled", False) else ("未启用" if config else "—")
    return info


def _resolve_theme(config):
    """把 ui.theme 配置解析为实际主题标签（浅色/深色），auto 跟随系统。"""
    mode = config.get("ui.theme") or "auto"
    from core.theme.base import resolve_dark
    return "深色" if resolve_dark(mode) else "浅色"


def validate_info(info: dict) -> list[str]:
    """校验采集结果，返回问题列表（空 = 全部正常；顺序稳定；绝不抛异常）。"""
    problems = []
    for key in ("GPU", "处理器"):
        v = info.get(key)
        if v is None or str(v).strip() == "":
            problems.append(f"{key} 为空")
    for key, v in info.items():
        if v == "未知":
            problems.append(f"{key} 为未知")
    mem = info.get("内存使用")
    if mem:
        used, total = _parse_mem_used_total(mem)
        if used is None or total is None:
            problems.append("内存使用格式异常")
        elif used > total:
            problems.append("内存使用超过总量")
    io = info.get("磁盘IO")
    if io and io != "未知":
        read, write = _parse_io_read_write(io)
        if read is None or write is None:
            problems.append("磁盘IO 格式异常")
        elif read < 0 or write < 0:
            problems.append("磁盘IO 出现负值")
    boot = info.get("系统启动时间")
    if boot and boot != "未知":
        try:
            datetime.datetime.fromisoformat(boot)
        except ValueError:
            problems.append("系统启动时间格式非法")
    return problems


def _parse_size(text):
    """解析 "20.0 GB" 式尺寸为数值；不可解析返回 None。"""
    m = re.match(r"^(-?[\d.]+)\s*(B|KB|MB|GB|TB|PB)$", text.strip(), re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1))


def _parse_mem_used_total(text):
    """解析 "used / total (...)" 为 (used, total)；不可解析返回 (None, None)。"""
    m = re.match(r"^(-?[\d.]+)\s*(B|KB|MB|GB|TB|PB)\s*/\s*(-?[\d.]+)\s*(B|KB|MB|GB|TB|PB)", text.strip(), re.IGNORECASE)
    if not m:
        return None, None
    return _parse_size(f"{m.group(1)} {m.group(2)}"), _parse_size(f"{m.group(3)} {m.group(4)}")


def _parse_io_read_write(text):
    """解析 "读 X / 写 Y" 为 (read, write)；不可解析返回 (None, None)。"""
    m = re.match(r"^读\s*(-?[\d.]+)\s*(B|KB|MB|GB|TB|PB)\s*/\s*写\s*(-?[\d.]+)\s*(B|KB|MB|GB|TB|PB)$", text.strip(), re.IGNORECASE)
    if not m:
        return None, None
    return _parse_size(f"{m.group(1)} {m.group(2)}"), _parse_size(f"{m.group(3)} {m.group(4)}")


def _fmt(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _cpu_brand():
    name = platform.processor()
    if name and name.strip():
        return name.strip()
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Processor | Select -Expand Name"],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000,
        )
        name = out.stdout.strip()
        return name if name else "未知"
    except Exception:
        return "未知"


def _gpu_names():
    import winreg
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}") as key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    i += 1
                    with winreg.OpenKey(key, sub) as sk:
                        try:
                            desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                            if desc and desc not in names:
                                names.append(desc)
                        except OSError:
                            pass
                except OSError:
                    break
    except OSError:
        pass
    return names


def _disk_summary():
    import psutil
    parts = []
    for p in psutil.disk_partitions():
        try:
            use = psutil.disk_usage(p.mountpoint)
            parts.append(f"{p.mountpoint} {_fmt(use.total)} ({use.percent}% 已用)")
        except OSError:
            parts.append(f"{p.mountpoint} 不可用")
    return "; ".join(parts)


def _pyside6_version():
    try:
        import PySide6
        return PySide6.__version__
    except Exception:
        return "未知"


def _qfw_version():
    try:
        import qfluentwidgets
        return getattr(qfluentwidgets, "__version__", "未知")
    except Exception:
        return "未知"


def _net_addrs():
    import psutil
    try:
        parts = []
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET:
                    parts.append(f"{name}: {a.address}")
        return "; ".join(parts) or "未知"
    except Exception:
        return "未知"


def _boot_time():
    import datetime
    import psutil
    try:
        return datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"


def _disk_io():
    import psutil
    try:
        io = psutil.disk_io_counters()
        if not io:
            return "未知"
        return f"读 {_fmt(io.read_bytes)} / 写 {_fmt(io.write_bytes)}"
    except Exception:
        return "未知"


def _make_info_widget(parent, config=None):
    from .sys_info_widget import make_info_widget
    return make_info_widget(parent, config)


MODULE_INFO = {
    "id": "sys_info",
    "name": "配置信息",
    "description": "读取电脑硬件与系统配置信息",
}


class Module(ModuleBase):
    MODULE_ID = "sys_info"
    MODULE_NAME = "配置信息"
    MODULE_DESCRIPTION = "读取电脑硬件与系统配置信息"

    def start(self):
        super().start()

    def stop(self):
        super().stop()

    def create_home_widget(self, parent):
        return _make_info_widget(parent)

    def create_page(self, parent):
        return _make_info_widget(parent, getattr(self.context, "config", None))

    def create_settings_widget(self, parent):
        return None