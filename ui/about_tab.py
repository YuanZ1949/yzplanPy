"""关于选项卡：Fluent 风格版本信息、更新检查、开发者信息。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, PrimaryPushButton, SubtitleLabel

_, QtCore, QtGui, QtWidgets = import_qt()

from core.constants import APP_NAME, APP_VERSION


class AboutTab:
    def __init__(self, context):
        self.context = context
        self.widget = QtWidgets.QWidget()
        self.widget.setObjectName("about_tab")
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(16, 16, 16, 16)

        title = SubtitleLabel(APP_NAME)
        layout.addWidget(title)

        html = (
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            f"<p>版本：{APP_VERSION}</p>"
            f"<p>Python GUI 程序：模块化主页 / 系统托盘 / 全局快捷键 / "
            f"资源管理器路径传递 / 系统信息 / RSS 聚合。</p>"
            f"<p>运行环境：Windows · PySide6 · Python 3.11 · PyQt-Fluent-Widgets</p>"
        )
        info = QtWidgets.QLabel(html)
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_update = PrimaryPushButton("检查更新")
        btn_update.clicked.connect(self._check_update)
        layout.addWidget(btn_update)

        dev = BodyLabel("开发者信息：YZplan 项目（开发者占位）")
        layout.addWidget(dev)
        layout.addStretch(1)

    def _check_update(self):
        QtWidgets.QMessageBox.information(self.widget, "检查更新", "更新检查接口尚未接入（Phase 4）。")