"""right_menu 首页小卡：经典菜单状态 + 账本两桶计数 + 打开详情页。

**刻意自动刷新，且刻意不起线程**——与 `proxy_ctrl` 首页卡正好相反，后者要起 `git`
子进程读代理目标，只能「用户点开才读」；本卡的数据源是一次 HKCU 读 + 一次 JSON 读，
都在毫秒级，为它起 QThread 只会多一层悬挂线程风险。所以 `tick()` 直接同步
`_render()` 并返 True，由 `Module` 的 `HOME_INTERVAL_MS` 定时器驱动。

**测试零真实注册表是硬约束**：经典状态经 `classic_getter` 注入点读，测试传
`lambda be: "enabled"` 即可完全不碰 `Win32Backend`；backend 也可整体注入。构造签名
里两个 kwarg 都是为此存在，生产路径的默认值分别落在 `classic.get_classic_state` 与
惰性 `Win32Backend()` 上（惰性是必须的：`Win32Backend()` 构造本身不碰注册表，但把它
钉死在类属性上会让「注入 backend」变得无从下手）。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_label, make_status_chip, make_tool_button

from .. import classic, store
from ..workers import TaskGroup

_, _QtCore, _QtGui, QtWidgets = import_qt()

#: 首页刷新间隔（ms）：30s。读注册表比 proxy 的 60s 便宜，但没必要更密
HOME_INTERVAL_MS = 30000

#: `classic.get_classic_state` 三态 → chip 文案。缺键（后端返了别的值）落「未知状态」
_CLASSIC_TEXT = {"enabled": "经典菜单", "disabled": "新版菜单", "unknown": "未知状态"}
_CLASSIC_TEXT_FALLBACK = "未知状态"


def home_summary(state, classic_state):
    """(账本, 经典状态) → 首页三项。纯函数，详情页与首页共用同一份解析口径。

    两个计数就是账桶长度，缺字段/None 一律降级为 0：首页没有失败态可展示，
    崩掉整张卡比显示「0」糟糕得多。
    """
    state = state or {}
    return {"classic": classic_state,
            "disabled_count": len(state.get("disabled") or []),
            "custom_count": len(state.get("custom_items") or [])}


class RightMenuHomeWidget(QtWidgets.QWidget):
    """首页小卡。`tick()` 由 Module 的定时器驱动（同步渲染，不起线程）。"""

    def __init__(self, owner, parent=None, *, backend=None, classic_getter=None):
        super().__init__(parent)
        self._owner = owner
        self._backend = backend              # None → _classic_backend() 惰性建
        self._classic_getter = classic_getter or classic.get_classic_state
        # TaskGroup 挂着不启动任务：销毁即 shutdown 是 AGENTS.md 硬要求，
        # 先把收口路径铺好，后续卡片要起任务时不必重写销毁链
        self._group = TaskGroup(self)
        self.setMinimumWidth(200)
        lay = QtWidgets.QVBoxLayout(self)
        pad = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.setSpacing(sizing()["radius_xs"])

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(sizing()["radius_xs"])
        head.addWidget(make_label("右键菜单", role="caption", parent=self))
        head.addStretch(1)
        self.btn_open = make_tool_button("打开", kind="ghost", size="sm", parent=self)
        self.btn_open.clicked.connect(self._open)
        head.addWidget(self.btn_open)
        lay.addLayout(head)

        self.chip = make_status_chip("未读取", kind="info", parent=self)
        lay.addWidget(self.chip)
        self.lb_disabled = self._add_row("已隐藏", "—")
        self.lb_custom = self._add_row("自定义", "—")
        self.destroyed.connect(self._stop)
        self._render()

    # ── 组装 ──────────────────────────────────────────────────
    def _add_row(self, name, value):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label(name, role="caption", parent=self))
        lb = make_label(value, role="body", parent=self)
        lb.setMinimumWidth(sizing()["btn_min_width"] * 2)
        row.addWidget(lb, 1)
        self.layout().addLayout(row)
        return lb

    # ── 数据 ──────────────────────────────────────────────────
    def _classic_backend(self):
        """惰性建真实后端：不在 import 期也不在 `__init__` 期碰 winreg。"""
        if self._backend is None:
            from ..registry_backend import Win32Backend

            self._backend = Win32Backend()
        return self._backend

    def _classic_state(self):
        """读经典菜单状态；后端永不抛异常，故调用方不必兜异常。"""
        return self._classic_getter(self._classic_backend())

    def _render(self):
        """重绘卡片（同步读账本 + 经典状态：无网络、无子进程、无线程）。"""
        summary = home_summary(store.load(), self._classic_state())
        self.lb_disabled.setText(str(summary["disabled_count"]))
        self.lb_custom.setText(str(summary["custom_count"]))
        self.chip.setText(_CLASSIC_TEXT.get(summary["classic"],
                                            _CLASSIC_TEXT_FALLBACK))

    def tick(self):
        """定时器回调：同步渲染一轮并返 True（恒成功，本地读不会失败）。"""
        self._render()
        return True

    # ── 动作与清理 ────────────────────────────────────────────
    def _open(self, *_args):
        from ui.module_pages import open_module_page
        try:
            open_module_page(self._owner, self)
        except RuntimeError:
            pass

    def _stop(self):
        """销毁即停：join 在跑任务，避免悬挂 QThread 让 pytest 永不退出。"""
        try:
            self._group.shutdown()
        except RuntimeError:
            pass
