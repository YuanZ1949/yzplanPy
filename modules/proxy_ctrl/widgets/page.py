"""proxy_ctrl 详情页：地址栏 + 3 个 Tab（代理目标 / 局域网扫描 / 测速与历史）。

> 250 行豁免说明（AGENTS.md 允许 page.py 超行，先例 modules/perf_monitor/page.py
> 472 行、modules/router_admin/widgets/page.py 304 行）：本文件是唯一的**装配层**
> —— 地址栏、记住的代理地址回填、标题栏契约、线程清理入口都在这里，拆开会让
> 生命周期割裂。可复用逻辑已全部下沉：表格工厂在 `widgets/tables.py`，令牌化控件
> 与确认框在 `widgets/__init__.py`，线程封装在 `workers.py`，三个标签页在
> `widgets/tab_*.py`。

**Tab 容器选型：QTabWidget**（不是 Pivot）。理由与 router_admin 一致：三个标签页
都是「参数区 + 重型表格」需要各自撑满剩余空间，stackedWidget 原生满足；全局 QSS
已用 `tab_*` 令牌统一 QTabBar 外观，本模块不覆写即可跟随明暗主题。

**构造阶段严禁发起网络请求**（`tests/test_proxy_ui.py` 用 monkeypatch 拦
`requests.get` 证明这一点）：`__init__` 只读本机 `store` 回填上次地址、搭控件。
读代理状态必须由用户点「读取状态」触发——它会起 `git` 子进程，离屏测试里不该
在构造期跑。所有耗时操作一律走 `workers.TaskGroup`。
"""
import os

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from qfluentwidgets import FluentIcon

from ui.widgets import make_button, make_card, make_label, make_line_edit

from .. import store
from ..targets import all_targets
from ..workers import TaskGroup
from . import confirm, notify
from .tab_scan import ScanTab
from .tab_speed import SpeedTab
from .tab_targets import TargetsTab

_, QtCore, QtGui, QtWidgets = import_qt()

#: Tab 顺序 → (属性名, 标题)
_TABS = (("targets", "代理目标"), ("scan", "局域网扫描"), ("speed", "测速与历史"))
#: 表格/内容区最小高度用 sizing 的哪个令牌
_TABS_MIN_H = "perf_tabs_min_height"


class ProxyPage(QtWidgets.QScrollArea):
    """代理控制详情页（frameless + 自定义标题栏）。"""

    frameless = True

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = TaskGroup(self)
        self._group.on_error = self._on_task_error
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content.setAutoFillBackground(True)
        self.setWidget(content)
        self.content = content
        lay = QtWidgets.QVBoxLayout(content)
        lay.setContentsMargins(sizing()["dialog_margin"] // 2,
                               sizing()["dialog_margin"] // 2,
                               sizing()["dialog_margin"] // 2,
                               sizing()["dialog_margin"] // 2)
        lay.setSpacing(sizing()["dialog_spacing"])
        lay.addWidget(self._build_addr_bar())
        self.tabs = QtWidgets.QTabWidget(content)
        self.targets = TargetsTab(owner, self._group, parent=self.tabs,
                                  url_provider=self.proxy_url,
                                  on_changed=self._on_targets_changed)
        self.scan = ScanTab(owner, self._group, parent=self.tabs,
                            on_use=self.use_proxy)
        self.speed = SpeedTab(owner, self._group, parent=self.tabs,
                              url_provider=self.proxy_url, on_use=self.use_proxy)
        for attr, title in _TABS:
            self.tabs.addTab(getattr(self, attr), title)
        self.tabs.setMinimumHeight(sizing().get(_TABS_MIN_H, 400))
        lay.addWidget(self.tabs, 1)
        self.footer = make_label("", role="caption", parent=content)
        lay.addWidget(self.footer)
        self._group.idle.connect(self._sync_enabled)
        self.destroyed.connect(self._shutdown)
        self._restore_url()
        self._sync_enabled()

    # ── 标题栏契约（ui/module_pages._ModuleWindow 消费）──────────
    @property
    def title_bar_spec(self):
        return {"buttons": [
            {"icon": FluentIcon.SYNC, "text": "读取状态",
             "tooltip": "读取全部代理目标当前的代理值", "cb": self.read_targets},
            {"icon": FluentIcon.FOLDER, "text": "数据目录",
             "tooltip": "打开本模块数据目录", "cb": self.open_data_dir},
        ], "widgets": False}

    # ── 地址栏 ──────────────────────────────────────────────────
    def _build_addr_bar(self):
        card = make_card(parent=self.content)
        outer = QtWidgets.QVBoxLayout(card)
        pad = sizing()["dialog_margin"] // 2
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(sizing()["radius_sm"])

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        self.edit_url = make_line_edit("代理地址，如 http://192.168.2.10:7890",
                                       parent=card)
        self.edit_url.returnPressed.connect(self.use_current_url)
        row.addWidget(make_label("代理地址", role="caption", parent=card))
        row.addWidget(self.edit_url, 1)
        self.btn_remember = make_button("记住地址", parent=card)
        self.btn_remember.clicked.connect(self.remember_url)
        self.btn_on = make_button("一键启用", kind="primary", parent=card)
        self.btn_on.clicked.connect(self.enable_all)
        self.btn_off = make_button("全部停用", kind="danger", parent=card)
        self.btn_off.clicked.connect(self.disable_all)
        for btn in (self.btn_remember, self.btn_on, self.btn_off):
            row.addWidget(btn)
        outer.addLayout(row)

        # 目标名一览：既让用户一眼看到本模块管哪些程序，也是各 Tab 的共同说明。
        names = "、".join(t.name for t in all_targets())
        names_lb = make_label(f"可管理的代理目标：{names}", role="caption",
                              parent=card)
        names_lb.setWordWrap(True)
        outer.addWidget(names_lb)
        self.hint = make_label("", role="caption", parent=card)
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)
        return card

    # ── 地址读写 ────────────────────────────────────────────────
    def proxy_url(self):
        """顶部地址框的当前内容（各 Tab 经 url_provider 拿它）。"""
        try:
            return (self.edit_url.text() or "").strip()
        except RuntimeError:                     # C++ 对象已析构
            return ""

    def use_proxy(self, url):
        """把 url 填进地址框并记住；同时把测速页的地址同步过去。"""
        if not url:
            return False
        try:
            self.edit_url.setText(url)
            self.speed.edit_url.setText(url)
        except RuntimeError:
            return False
        self._note(f"已填入代理地址：{url}。可在「代理目标」页点「设为当前」逐项写入，"
                   f"或点「一键启用」全部写入。")
        return True

    def use_current_url(self, *_args):
        """地址框回车：填值后立刻测速（用户最常见的下一步动作）。"""
        return self.speed.test()

    def remember_url(self, *_args):
        url = self.proxy_url()
        if not url:
            self._note("地址框为空，没有可记住的代理地址。")
            return False
        if store.remember_proxy_url(url):
            self._note(f"已记住代理地址 {url}，下次打开会自动填入。")
        else:
            notify(self, "记忆失败", "无法写入本机数据目录，请检查权限。",
                   error=True)
        return False

    def _restore_url(self):
        """回填上次用过的地址。纯本地读文件，不联网、不起子进程。"""
        url = store.get_last_proxy_url()
        if url:
            self.edit_url.setText(url)
            self.speed.edit_url.setText(url)
        self.speed.refresh_history()

    # ── 动作 ────────────────────────────────────────────────────
    def read_targets(self, *_args):
        """标题栏「读取状态」与各 Tab 内部的读取共用一个动作。"""
        self.tabs.setCurrentIndex(0)
        return self.targets.refresh()

    def _on_targets_changed(self, rows=None):
        """目标表读/写完成：把最新快照推给首页小卡（跨页共享同一份数据源）。"""
        if rows is not None:
            self._owner.record_targets(rows)
        else:
            self.targets.refresh()

    def enable_all(self, *_args):
        """一键把地址写进全部 7 个目标（对应原版菜单 3）。"""
        url = self.proxy_url()
        if not url:
            self._note("请先在地址框填入代理地址，例如 http://192.168.2.10:7890。")
            notify(self, "缺少代理地址", "地址框为空，无法写入。", error=True)
            return False
        if not confirm(self, "一键启用全局代理",
                       f"把 {url} 写入全部代理目标：\n\n"
                       f"· Git → git config --global（持久化）\n"
                       f"· cURL / wget / Python / Node.js / 全局 → "
                       f"HKCU\\Environment 并广播 WM_SETTINGCHANGE\n"
                       f"· Docker → 已存在的 daemon.json 的 proxies 节点\n\n"
                       f"环境变量类改动**只对新开的程序生效**，已运行的程序不受影响。\n\n"
                       f"确认写入？", ok_text="全部写入"):
            return False
        self.tabs.setCurrentIndex(0)
        if not self.targets.apply_all("set", url):
            self._note("上一项任务还没结束，请稍后再点「一键启用」。")
        else:
            self._note(f"正在把 {url} 写入全部目标…")
        return True

    def disable_all(self, *_args):
        """全部停用（对应原版菜单 4）。不需要填地址。"""
        if not confirm(self, "停用全部代理",
                       "将清除全部代理目标当前的代理设置：\n\n"
                       "· Git → git config --global --unset\n"
                       "· 环境变量类 → 从 HKCU\\Environment 删除并广播\n"
                       "· Docker → 移除 daemon.json 的 proxies 节点\n\n"
                       "确认停用？", ok_text="全部停用"):
            return False
        self.tabs.setCurrentIndex(0)
        if not self.targets.apply_all("unset"):
            self._note("上一项任务还没结束，请稍后再点「全部停用」。")
        else:
            self._note("正在清除全部目标的代理设置…")
        return True

    def open_data_dir(self, *_args):
        try:
            os.startfile(store.data_dir())   # noqa: S606 - Windows 专有，仅本机开目录
        except (OSError, AttributeError):
            notify(self, "无法打开目录", "当前系统不支持 os.startfile。",
                   error=True)
        return True

    # ── 状态与清理 ──────────────────────────────────────────────
    def _note(self, text):
        self.hint.setText(text)
        self.footer.setText(text)

    def _sync_enabled(self):
        """一轮任务结束：恢复按钮，扫描结果落盘后刷新历史表。"""
        busy = self._group.busy
        for btn in (self.btn_on, self.btn_off, self.btn_remember):
            btn.setEnabled(not busy)
        self.targets.btn_read.setEnabled(not busy)
        self.speed.btn_test.setEnabled(not busy)
        try:
            self.speed.refresh_history()
        except RuntimeError:
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
