"""SettingsTab 核心：MCP 跨线程桥接信号与主界面装配（外观/行为/MCP/日志卡片）。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import StrongBodyLabel
_, QtCore, QtGui, QtWidgets = import_qt()

class _MCPBridge(QtCore.QObject):
    """把后台线程的测试结果安全投递回主线程（QueuedConnection 自动按线程排队）。"""
    done = QtCore.Signal(bool, str)


class SettingsTab:
    def __init__(self, context):
        self.context = context
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("settings_tab")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(12, 12, 12, 12)

        header = StrongBodyLabel("程序设置")
        layout.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QtWidgets.QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(12)

        appearance_card = self._make_card(il, "外观")
        self.theme_combo = self._make_theme_row(appearance_card)
        self._make_wallpaper_row(appearance_card)
        self._make_acrylic_row(appearance_card)
        self._make_opacity_row(appearance_card)
        self._make_blur_radius_row(appearance_card)
        self._make_glass_opacity_row(appearance_card)

        behavior_card = self._make_card(il, "行为")
        self.cb_autostart = self._make_switch_row(behavior_card, "开机自动启动", "登录时在后台启动")
        self.cb_close_tray = self._make_switch_row(behavior_card, "关闭窗口时最小化到系统托盘", "窗口关闭后程序驻留托盘")
        self.cb_start_hidden = self._make_switch_row(behavior_card, "启动时隐藏主界面（仅显示托盘）", "开机自启时不弹出主窗口")

        mcp_card = self._make_card(il, "MCP 服务器")
        self._build_mcp_section(mcp_card)

        log_card = self._make_card(il, "运行日志")
        self._build_log_section(log_card)

        il.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self._mcp_bridge = _MCPBridge()
        self._mcp_bridge.done.connect(self._on_mcp_result, QtCore.Qt.QueuedConnection)
        self._load()
