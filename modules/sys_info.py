"""sys_info 模块：读取电脑配置信息。"""
import platform
import socket

from .base import ModuleBase


def collect_info():
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
    return info


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


def _make_info_widget(parent):
    from .sys_info_widget import make_info_widget
    return make_info_widget(parent)


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

    def create_settings_widget(self, parent):
        return None