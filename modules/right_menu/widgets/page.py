"""right_menu 详情页：五个标签（右键项 / 新建菜单 / 经典菜单 / 自定义项 / 设置）。

**Tab 容器选型：QTabWidget**（不是 Pivot）。理由与 proxy_ctrl/router_admin 一致：五个
标签页都是「参数区 + 重型表格」需要各自撑满剩余空间，stackedWidget 原生满足；全局
QSS 已用 `tab_*` 令牌统一 QTabBar 外观，本模块不覆写即可跟随明暗主题。

**页面是 backend 的单一来源**：`self.backend` 建一次（未注入才惰性建 `Win32Backend`），
每个标签一律以 `backend=` kwarg 传下去。标签自己再惰性建后端就会出现「一个页面两个
注册表视图」的窗口期，且测试也就没法整体注入 `FakeRegistry`。

**构造阶段严禁碰注册表的重操作、也不许起线程**（`tests/test_right_menu_ui.py` 用
FakeRegistry + 不起线程的构造路径覆盖这一点）：`__init__` 只搭控件，扫描/隐藏/恢复/切换/
重启一律由用户点按钮触发、经 `workers.TaskGroup` 走后台线程。**唯一的例外**是三个真标签
里的 `ClassicTab`：它在构造尾同步读一次经典状态（毫秒级 HKCU 取值，`Win32Backend` 永不
抛且读不到即降级），为的是标签一打开就显示当前风格——这仍是「读」，不是重操作。

**「右键项」「新建菜单」「经典菜单」「自定义项」已是真实标签**，最后一个（设置）先用占位
QWidget 铺满标签位（后续任务替换）。占位不是临时代码凑数：标签位与 `title_bar_spec`
在本任务就定型，占位能让后续任务只改一个文件、不动页面装配层。

**`CustomTab` 是第四个真标签**：它的账本是本地 JSON，故构造尾同步 `refresh()` 一次即显示当前
自定义项（与 `ClassicTab` 同步读 HKCU 同一判断，见上）。设置标签落成真实现时，只需把 `_TABS[4]`
从占位循环里挪出来加 `addTab`、并把 `_TABS[5:]` 留给后续标签。
"""
import os

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from qfluentwidgets import FluentIcon

from ui.widgets import make_label

from .. import store
from ..workers import TaskGroup
from . import notify
from .page_tabs import ClassicTab, CustomTab, ScanTab, ShellNewTab

_, QtCore, QtGui, QtWidgets = import_qt()

#: Tab 顺序 → (属性名, 标题)。属性名只在标签是真实实现时用得上
#: （scan / shellnew / classic / custom；settings 仍走占位）。
_TABS = (("scan", "右键项"), ("shellnew", "新建菜单"), ("classic", "经典菜单"),
         ("custom", "自定义项"), ("settings", "设置"))
#: 标签容器最小高度用 sizing 的哪个令牌
_TABS_MIN_H = "perf_tabs_min_height"


def _placeholder(title):
    """尚未上线的标签占位：一个居中说明 label 的 QWidget（后续任务逐个替换）。"""
    page = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(page)
    lay.addStretch(1)
    label = make_label(f"{title}：即将上线", role="caption", parent=page)
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(label)
    lay.addStretch(1)
    return page


class RightMenuPage(QtWidgets.QScrollArea):
    """右键菜单管理详情页（frameless + 自定义标题栏）。"""

    frameless = True

    def __init__(self, owner, parent=None, *, backend=None):
        super().__init__(parent)
        self._owner = owner
        # backend 惰性建：不注入就建 Win32Backend（测试注入 FakeRegistry）
        if backend is None:
            from ..registry_backend import Win32Backend
            backend = Win32Backend()
        self.backend = backend
        self._group = TaskGroup(self)
        self._group.on_error = self._on_task_error
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content.setAutoFillBackground(True)
        self.setWidget(content)
        self.content = content
        lay = QtWidgets.QVBoxLayout(content)
        margin = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.setSpacing(sizing()["dialog_spacing"])
        self.tabs = QtWidgets.QTabWidget(content)
        self.scan = ScanTab(owner, self._group, parent=self.tabs, page=self,
                            backend=self.backend)
        self.shellnew = ShellNewTab(owner, self._group, parent=self.tabs, page=self,
                                    backend=self.backend)
        self.classic = ClassicTab(owner, self._group, parent=self.tabs, page=self,
                                  backend=self.backend)
        self.custom = CustomTab(owner, self._group, parent=self.tabs, page=self,
                                backend=self.backend)
        self.tabs.addTab(self.scan, _TABS[0][1])
        self.tabs.addTab(self.shellnew, _TABS[1][1])
        self.tabs.addTab(self.classic, _TABS[2][1])
        self.tabs.addTab(self.custom, _TABS[3][1])
        for _attr, title in _TABS[4:]:
            self.tabs.addTab(_placeholder(title), title)
        self.tabs.setMinimumHeight(sizing().get(_TABS_MIN_H, 400))
        lay.addWidget(self.tabs, 1)
        self.footer = make_label("", role="caption", parent=content)
        lay.addWidget(self.footer)
        self._group.idle.connect(self._sync_enabled)
        self.destroyed.connect(self._shutdown)

    # ── 标题栏契约（ui/module_pages._ModuleWindow 消费）──────────
    @property
    def title_bar_spec(self):
        return {"buttons": [
            {"icon": FluentIcon.SYNC, "text": "刷新",
             "tooltip": "重新扫描当前标签数据", "cb": self.refresh},
            {"icon": FluentIcon.FOLDER, "text": "数据目录",
             "tooltip": "打开本模块数据目录", "cb": self.open_data_dir},
        ], "widgets": False}

    # ── 动作 ──────────────────────────────────────────────────
    def refresh(self, *_args):
        """标题栏「刷新」：转发给当前标签（各标签自己决定刷什么；占位标签跳过）。"""
        widget = self.tabs.currentWidget()
        return widget.refresh() if hasattr(widget, "refresh") else False

    def open_data_dir(self, *_args):
        """打开账本所在目录（`store.STATE_PATH` 调用时读，便于测试隔离）。"""
        try:
            os.startfile(os.path.dirname(store.STATE_PATH))   # noqa: S606
        except (OSError, AttributeError):
            notify(self, "无法打开目录", "当前系统不支持 os.startfile。",
                   error=True)
            return False
        return True

    # ── 状态与清理 ──────────────────────────────────────────────
    def _note(self, text):
        self.footer.setText(text)

    def _sync_enabled(self):
        """一轮任务结束：把「忙」态解禁工作交给各标签自己（按钮各不相同）。

        逐个 try：某个标签的 C++ 对象已析构时不能连累后面的标签解禁。
        """
        for _tab in (self.scan, self.shellnew, self.classic, self.custom):
            try:
                _tab.on_idle()
            except RuntimeError:             # C++ 对象已析构
                pass

    def _on_task_error(self, kind, text):
        self._note(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

    def _shutdown(self):
        """页面销毁：中断并 join 所有在跑线程（AGENTS.md 硬要求）。"""
        try:
            self._group.shutdown()
        except RuntimeError:
            pass

    def paintEvent(self, event):
        p = theme_palette()
        painter = QtGui.QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QtGui.QColor(p["bg_app"]))
        painter.end()
        super().paintEvent(event)
