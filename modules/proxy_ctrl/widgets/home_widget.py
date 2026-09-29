"""proxy_ctrl 首页小卡：当前全局代理 + 已启用的目标数 + 打开详情页。

刻意**不自动刷新**：首页在无人值守时会常驻，而读代理状态要起 `git` 子进程、读
注册表。改为「用户点开小卡才读一次」——`Module` 的定时器只在首页小卡可见时
驱动 `tick()`，且距上次读取不足 HOME_INTERVAL_MS 就跳过。

数据源统一是 `Module.snapshot`（详情页与本页共用），本页只读不改：
`snapshot["proxy_url"]` / `["active"]` / `["tried"]` 由详情页写入。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_label, make_status_chip, make_tool_button

from ..targets import all_targets
from ..workers import TaskGroup, read_targets_worker

_, QtCore, QtGui, QtWidgets = import_qt()

#: 首页读取状态的最小间隔（ms）：无意义高频起 git 子进程
HOME_INTERVAL_MS = 60000
#: 已启用目标数 ≥ 该值时显示「已启用」chip，否则「未设置」
_ACTIVE_MIN = 1


def home_summary(rows):
    """read_targets_worker 的结果 → 首页卡片三项（与详情页共用同一份解析层）。"""
    rows = list(rows or [])
    url = next((r.get("value") for r in rows if r.get("value")), "")
    return {"proxy_url": url, "active": sum(1 for r in rows if r.get("value")),
            "total": len(rows)}


class ProxyHomeWidget(QtWidgets.QWidget):
    """首页小卡。`tick()` 由 Module 的定时器驱动（后台线程读状态）。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = TaskGroup(self)
        self.setMinimumWidth(200)
        lay = QtWidgets.QVBoxLayout(self)
        pad = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(sizing()["radius_xs"])

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(sizing()["radius_xs"])
        head.addWidget(make_label("代理", role="caption", parent=self))
        head.addStretch(1)
        self.btn_open = make_tool_button("打开", kind="ghost", size="sm",
                                         parent=self)
        self.btn_open.clicked.connect(self._open)
        head.addWidget(self.btn_open)
        lay.addLayout(head)

        self.chip = make_status_chip("未读取", kind="info", parent=self)
        lay.addWidget(self.chip)
        self.lb_url = self._add_row("地址", "—")
        self.lb_active = self._add_row("目标", f"— / {len(all_targets())}")
        self.destroyed.connect(self._stop)
        self._render()

    def _add_row(self, name, value):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label(name, role="caption", parent=self))
        lb = make_label(value, role="body", parent=self)
        lb.setMinimumWidth(sizing()["btn_min_width"] * 2)
        row.addWidget(lb, 1)
        self.layout().addLayout(row)
        return lb

    def _render(self):
        """按 owner.snapshot 重绘卡片（纯本地渲染，无网络、无子进程）。"""
        snap = self._owner.snapshot or {}
        url = str(snap.get("proxy_url") or "")
        active = int(snap.get("active") or 0)
        self.lb_url.setText(url or "—")
        self.lb_active.setText(f"{active} / {snap.get('total', len(all_targets()))}")
        if url:
            self.chip.setText("已启用")
        elif snap.get("tried"):
            self.chip.setText("未设置")
        else:
            self.chip.setText("未读取")

    def tick(self):
        """定时器回调：距上次读取不到 HOME_INTERVAL_MS 或上一轮未结束就跳过。"""
        if self._group.busy:
            return False
        now = QtCore.QDateTime.currentMSecsSinceEpoch()
        if self._owner.last_read_ms and now - self._owner.last_read_ms < HOME_INTERVAL_MS:
            return False
        self._owner.last_read_ms = now
        return self._group.start(read_targets_worker, on_ok=self._applied,
                                 on_err=self._failed, label="home")

    def _applied(self, data):
        summary = home_summary(data.get("rows"))
        self._owner.snapshot = dict(self._owner.snapshot or {}, tried=True,
                                    **summary)
        self._render()

    def _failed(self, kind, text):
        self._owner.snapshot = dict(self._owner.snapshot or {}, tried=True)
        self._render()
        self.setToolTip(f"最近一次读取失败（{kind}）：{text}")

    def _open(self, *_args):
        from ui.module_pages import open_module_page
        try:
            open_module_page(self._owner, self)
        except RuntimeError:
            pass

    def _stop(self):
        """销毁即停：中断并 join 线程，避免悬挂 QThread 让 pytest 永不退出。"""
        try:
            self._group.shutdown()
        except RuntimeError:
            pass
