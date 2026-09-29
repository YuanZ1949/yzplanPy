"""router_admin 详情页：连接栏 + 4 个 Tab。

> 250 行豁免说明（AGENTS.md 允许 page.py 超行，先例 modules/perf_monitor/page.py
> 472 行）：本文件是唯一的**装配层**——连接栏、连接状态机、自动刷新时钟、标题栏
> 契约、线程清理入口都在这里，拆开反而让生命周期割裂。可复用逻辑已全部下沉：
> 表格工厂在 `widgets/tables.py`，令牌化控件与确认框在 `widgets/__init__.py`，
> 线程封装在 `workers.py`，采集/解析/渲染在 `widgets/tabs_*.py`。

**Tab 容器选型：QTabWidget**（不是 Pivot）。理由：①四个标签页内容都是「标题 + 表格
+ 一排按钮」的重型布局，需要各自撑满剩余空间，QTabWidget 的 stackedWidget 原生满足，
Pivot 只适合少量互斥视图的切换；②全局 QSS（core/theme/qss_*.py）已用 tab_* 令牌统一
了 QTabBar 外观，本模块不覆写即可自动跟随明暗主题；③perf_monitor 页面已用 QTabWidget，
保持一致的观感与键盘/无障碍行为。

**构造阶段严禁发起网络连接**：__init__ 只读本地 store 填默认值、搭控件，
连接必须由用户点「连接」触发（离屏构造测试因此不会卡在 8 秒 connect 上）。
"""
import os

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from qfluentwidgets import FluentIcon, SpinBox

from ui.widgets import (make_button, make_card, make_checkbox, make_label,
                        make_line_edit, make_status_chip)

from .. import store
from ..connection import (ConnectionError_, ConnectionParams, DEFAULT_INTERVAL,
                          DEFAULT_PORT, MAX_INTERVAL, MIN_INTERVAL,
                          is_allowed_config)
from ..workers import TaskGroup
from . import make_password_edit, notify
from .tabs_clients import ClientsTab
from .tabs_config import ConfigTab
from .tabs_overview import OverviewTab
from .tabs_services import ServicesTab

_, QtCore, QtGui, QtWidgets = import_qt()

#: 失败分类 → 提示标题（describe_error 给出的分类在此映射成可读标题）
ERROR_TITLES = {
    "login": "登录失败", "connect": "连接失败", "timeout": "响应超时",
    "session": "会话中断", "unknown": "操作失败",
}

#: 状态 chip：状态名 → (文字, chip kind)
STATES = {
    "offline": ("离线", "error"),
    "connecting": ("连接中…", "info"),
    "busy": ("采集中…", "info"),
    "online": ("在线", "success"),
}


class RouterPage(QtWidgets.QScrollArea):
    """路由器管理详情页（frameless + 自定义标题栏）。"""

    frameless = True

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = TaskGroup(self)
        self._group.on_error = self._on_task_error
        self._group.on_success = self._on_task_ok
        self._state = "offline"
        self._chip_kind = None
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content.setAutoFillBackground(True)
        self.setWidget(content)
        self.content = content
        lay = QtWidgets.QVBoxLayout(content)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(sizing()["dialog_spacing"])
        lay.addWidget(self._build_conn_bar())
        self.tabs = QtWidgets.QTabWidget(content)
        self.overview = OverviewTab(owner, self._group, parent=self.tabs)
        self.clients = ClientsTab(owner, self._group, parent=self.tabs)
        self.services = ServicesTab(owner, self._group, parent=self.tabs)
        self.config = ConfigTab(owner, self._group, parent=self.tabs)
        for widget, title in ((self.overview, "总览"), (self.clients, "在线终端"),
                              (self.services, "服务管理"), (self.config, "配置编辑")):
            self.tabs.addTab(widget, title)
        self.tabs.setMinimumHeight(sizing()["perf_tabs_min_height"])
        lay.addWidget(self.tabs, 1)
        self.footer = make_label("", role="caption", parent=content)
        lay.addWidget(self.footer)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._group.idle.connect(self._on_idle)
        self.destroyed.connect(self._shutdown)
        self._load_settings()
        self._set_state("offline")
        self._sync_enabled()

    # ── 标题栏契约（ui/module_pages._ModuleWindow 消费）──────────
    @property
    def title_bar_spec(self):
        return {"buttons": [
            {"icon": FluentIcon.SYNC, "text": "刷新",
             "tooltip": "立即刷新状态", "cb": self._refresh_now},
            {"icon": FluentIcon.FOLDER, "text": "数据目录",
             "tooltip": "打开本模块数据目录", "cb": self._open_data_dir},
        ], "widgets": False}

    # ── 连接栏 ──────────────────────────────────────────────────
    def _build_conn_bar(self):
        card = make_card(parent=self.content)
        outer = QtWidgets.QVBoxLayout(card)
        pad = sizing()["dialog_margin"] // 2
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(sizing()["radius_sm"])
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(sizing()["radius_sm"])
        self.edit_host = make_line_edit("主机", parent=card)
        self.edit_port = make_line_edit("端口", parent=card)
        self.edit_port.setMaximumWidth(sizing()["btn_min_width"])
        self.edit_user = make_line_edit("用户", parent=card)
        self.edit_pass = make_password_edit("口令（DPAPI 加密保存）", parent=card)
        self.edit_pass.setMinimumWidth(sizing()["btn_min_width"] * 2)
        self.chk_show = make_checkbox("显示", parent=card)
        self.chk_show.toggled.connect(self._toggle_pass)
        for label, widget in (("主机", self.edit_host), ("端口", self.edit_port),
                              ("用户", self.edit_user), ("口令", self.edit_pass)):
            row1.addWidget(make_label(label, role="caption", parent=card))
            row1.addWidget(widget)
        row1.addWidget(self.chk_show)
        self.btn_conn = make_button("连接", kind="primary", parent=card)
        self.btn_conn.clicked.connect(self._on_connect)
        self.btn_disc = make_button("断开", parent=card)
        self.btn_disc.clicked.connect(self._on_disconnect)
        row1.addWidget(self.btn_conn)
        row1.addWidget(self.btn_disc)
        row1.addStretch(1)
        self._chip_slot = row1
        self.chip = None
        outer.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(sizing()["radius_sm"])
        self.chk_auto = make_checkbox("自动刷新", parent=card)
        self.chk_auto.toggled.connect(self._on_auto_changed)
        row2.addWidget(self.chk_auto)
        row2.addWidget(make_label("间隔", role="caption", parent=card))
        self.spin = SpinBox(card)
        self.spin.setRange(MIN_INTERVAL, MAX_INTERVAL)
        self.spin.setValue(DEFAULT_INTERVAL)
        self.spin.setSuffix(" 秒")
        self.spin.valueChanged.connect(self._on_interval_changed)
        row2.addWidget(self.spin)
        self.btn_now = make_button("立即刷新", parent=card)
        self.btn_now.clicked.connect(self._refresh_now)
        row2.addWidget(self.btn_now)
        row2.addStretch(1)
        self.hint = make_label("", role="caption", parent=card)
        row2.addWidget(self.hint)
        outer.addLayout(row2)
        return card

    # ── 设置持久化（口令由 store 用 DPAPI 加密，UI 不落明文）────
    def _load_settings(self):
        data = store.load()
        self.edit_host.setText(str(data.get("host") or ""))
        self.edit_port.setText(str(data.get("port") or DEFAULT_PORT))
        self.edit_user.setText(str(data.get("user") or ""))
        self.chk_auto.setChecked(bool(data.get("auto_refresh")))
        self.spin.setValue(int(data.get("interval") or DEFAULT_INTERVAL))
        if data.get("password"):
            # 口令**绝不回填进输入框**：输入框内容是可被截图/读内存拿到的明文。
            # 留空即可——_collect_params 会回落到 store 里的 DPAPI 密文解密结果。
            self.edit_pass.setPlaceholderText("已保存口令，留空即直接使用")
            self.hint.setText("检测到已保存的口令（DPAPI 加密存储），留空即可直接连接。")
        else:
            self.edit_pass.setPlaceholderText("口令（DPAPI 加密保存）")
            self.hint.setText(
                "未找到可用的已保存口令（换机器/换用户时 DPAPI 必然解密失败），"
                "请重新填写后再连接。")
        self._owner.wan_iface = str(data.get("wan_iface") or "pppoe-wan")
        self._owner.lan_iface = str(data.get("lan_iface") or "br-lan")

    def _collect_params(self):
        """读输入框 → 校验。失败抛 ConnectionError_（就地报错，不发线程）。"""
        stored = store.load()
        params = ConnectionParams(
            host=self.edit_host.text().strip(), port=self.edit_port.text().strip(),
            user=self.edit_user.text().strip(),
            password=self.edit_pass.text() or (stored.get("password") or ""),
            connect_timeout=stored.get("connect_timeout"),
            read_timeout=stored.get("read_timeout"))
        params.validate()
        return params

    def _persist(self):
        """把当前输入写回 store。口令只在用户填了新的明文时替换密文。"""
        data = store.load()
        data.update({
            "host": self.edit_host.text().strip(),
            "port": self.edit_port.text().strip() or DEFAULT_PORT,
            "user": self.edit_user.text().strip(),
            "auto_refresh": bool(self.chk_auto.isChecked()),
            "interval": int(self.spin.value())})
        if self.edit_pass.text():
            data["password"] = self.edit_pass.text()
        if not store.save(data) and self.edit_pass.text():
            self.hint.setText("口令保存失败（DPAPI 不可用），本次仍可连接但不记忆。")
        return data

    # ── 连接状态机 ──────────────────────────────────────────────
    def _on_connect(self):
        if self._group.busy:
            self.hint.setText("上一轮任务还在跑，请等它结束。")
            return
        try:
            params = self._collect_params()
        except ConnectionError_ as exc:
            self.hint.setText(f"参数不合法：{exc}")
            notify(self, "参数不合法", str(exc), error=True)
            return
        if not is_allowed_config("network"):        # 白名单自检，异常环境直接拦写
            self.hint.setText("配置白名单异常，已禁止一切写操作。")
            return
        self._persist()
        self._group.set_params(params)
        self._set_state("connecting")
        self._sync_enabled()
        self._refresh_now()

    def _on_disconnect(self):
        self._timer.stop()
        self._group.set_params(None)
        self._owner.mark_offline()
        self._set_state("offline")
        self._sync_enabled()
        self.hint.setText("已断开。")

    def _refresh_now(self, *_args):
        """标题栏「刷新」与「立即刷新」共用。带参是因为 clicked 会传 bool。"""
        if self._group.busy or self._group.params is None:
            self.hint.setText("未连接或正在采集中，稍后再试。")
            return False
        if not self.overview.refresh():
            self.hint.setText("采集任务未能启动。")
            return False
        self._set_state("busy")
        self._sync_enabled()
        return True

    def _current_tab(self):
        return (self.overview, self.clients, self.services,
                self.config)[self.tabs.currentIndex()]

    def _on_tick(self):
        """自动刷新：只刷当前标签页（总览最常用），忙则跳过本轮。"""
        if self._group.busy or self._group.params is None:
            return
        self._current_tab().refresh()

    def _on_auto_changed(self, _on):
        self._apply_interval()
        self._persist()

    def _on_interval_changed(self, _value):
        self._apply_interval()
        self._persist()

    def _apply_interval(self):
        self._timer.setInterval(int(self.spin.value()) * 1000)
        if self.chk_auto.isChecked() and self._group.params is not None:
            self._timer.start()
        else:
            self._timer.stop()

    def _toggle_pass(self, on):
        self.edit_pass.setEchoMode(
            QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password)

    def _set_state(self, state):
        self._state = state
        text, kind = STATES.get(state, STATES["offline"])
        self._owner.state = state
        if kind == self._chip_kind and self.chip is not None:
            self.chip.setText(text)
            return
        self._chip_kind = kind
        old = self.chip
        self.chip = make_status_chip(text, kind=kind, parent=self.content)
        self._chip_slot.insertWidget(self._chip_slot.count() - 1, self.chip)
        if old is not None:
            old.setParent(None)
            old.deleteLater()

    def _sync_enabled(self):
        connected = self._group.params is not None
        busy = self._group.busy
        self.btn_conn.setEnabled(not busy)
        self.btn_disc.setEnabled(connected)
        self.btn_now.setEnabled(connected and not busy)
        for edit in (self.edit_host, self.edit_port, self.edit_user, self.edit_pass):
            edit.setEnabled(not busy)
        self.services.set_connected(connected and not busy)
        if not connected:
            self._timer.stop()

    def _on_task_ok(self):
        self._owner.mark_online()

    def _on_idle(self):
        """一轮任务结束：按 owner.state 收敛显示态并恢复按钮。"""
        self._set_state("online" if self._owner.state == "online" else "offline")
        self._sync_enabled()

    def _on_task_error(self, kind, text):
        self._owner.mark_offline()
        self._set_state("offline")
        self._sync_enabled()
        self.hint.setText(text.replace("\n", " "))
        notify(self, ERROR_TITLES.get(kind, "操作失败"), text, error=True)

    def _open_data_dir(self, *_args):
        try:
            os.startfile(store.data_dir())   # noqa: S606 - Windows 专有，仅本机开目录
        except (OSError, AttributeError):
            notify(self.content, "无法打开目录", "当前系统不支持 os.startfile。",
                   error=True)

    def _shutdown(self):
        """页面销毁：停时钟 + 中断并 join 所有在跑线程（AGENTS.md 硬要求）。"""
        try:
            self._timer.stop()
        except RuntimeError:
            pass
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
