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
    return info


def _fmt(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _cpu_brand():
    try:
        import subprocess
        out = subprocess.run(["wmic", "cpu", "get", "Name"], capture_output=True, text=True, creationflags=0x08000000)
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip() and not l.startswith("Name")]
        return lines[0] if lines else ""
    except Exception:
        return ""


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


def _make_info_widget(parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(6)

    table = QtWidgets.QTableWidget()
    info = collect_info()
    table.setRowCount(len(info))
    table.setColumnCount(2)
    table.setHorizontalHeaderLabels(["项目", "值"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
    table.verticalHeader().setDefaultSectionSize(26)

    for row, (k, v) in enumerate(info.items()):
        key_item = QtWidgets.QTableWidgetItem(k)
        key_item.setFont(QtGui.QFont("", -1, QtGui.QFont.Bold))
        val_item = QtWidgets.QTableWidgetItem(str(v))
        table.setItem(row, 0, key_item)
        table.setItem(row, 1, val_item)

    table.setStyleSheet(
        "QTableWidget { border: none; gridline-color: transparent; }"
        "QTableWidget::item { padding: 2px 4px; }"
    )
    lay.addWidget(table, 1)

    btn = QtWidgets.QPushButton("刷新")
    btn.clicked.connect(lambda: _refresh_table(table))
    lay.addWidget(btn)
    return w


def _refresh_table(table):
    info = collect_info()
    table.setRowCount(len(info))
    for row, (k, v) in enumerate(info.items()):
        key_item = QtWidgets.QTableWidgetItem(k)
        key_item.setFont(QtGui.QFont("", -1, QtGui.QFont.Bold))
        val_item = QtWidgets.QTableWidgetItem(str(v))
        table.setItem(row, 0, key_item)
        table.setItem(row, 1, val_item)


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