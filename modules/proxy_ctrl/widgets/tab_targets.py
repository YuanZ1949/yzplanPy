"""proxy_ctrl.widgets.tab_targets：代理目标矩阵（读 / 设 / 清）。

移植自 toggle_proxy「全能代理管理器 v3.2」菜单的 4~10 项（停用 + 六个单目标
设置 + 全局），这里收敛成一张表：每个 `targets.ProxyTarget` 一行，逐项设/清。

**构造与读取阶段都不联网**：读状态只走 `git config --global` 子进程、winreg
读 HKCU\\Environment、以及读本机 daemon.json，三者都不碰 `requests`。写操作
（set / unset）会起 git 进程、改注册表与写文件，故同样走后台线程。

本文件只做「渲染 + 点线」，命令与地址一律由纯逻辑层构造。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label

from .. import workers
from . import confirm, make_card_block, notify, summarize
from .tables import fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

#: 表头列序（与 fill_table 的 columns 一一对应）
HEADERS = ("目标", "当前代理", "状态", "说明", "操作")
#: 未设置代理时「当前代理」列的占位
_EMPTY = "未设置"
#: 操作列按钮 → 动作名。与 `workers.apply_target_worker` 的 action 参数同域。
ACT_SET, ACT_UNSET = "set", "unset"


class TargetsTab(QtWidgets.QWidget):
    """代理目标表。`refresh()` 读全部目标；`apply_all()` 批量设/清。"""

    def __init__(self, owner, group, *, parent=None, url_provider=None,
                 on_changed=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._url_provider = url_provider or (lambda: "")
        self._on_changed = on_changed
        self._rows = []
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])

        card, lay = make_card_block(None, parent=self)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(sizing()["radius_sm"])
        bar.addWidget(make_label("代理目标", role="caption", parent=card))
        bar.addStretch(1)
        self.btn_read = make_button("读取状态", parent=card)
        self.btn_read.clicked.connect(self.refresh)
        bar.addWidget(self.btn_read)
        lay.addLayout(bar)
        self.table = make_table(HEADERS, parent=card)
        lay.addWidget(self.table)
        self.hint = make_label("尚未读取。点「读取状态」查看各目标当前的代理。",
                               role="caption", parent=card)
        lay.addWidget(self.hint)
        root.addWidget(card)

    # ── 读 ──────────────────────────────────────────────────────
    def refresh(self):
        """后台读全部目标。构造阶段**不**自动调用（避免离屏测试里起 git 进程）。"""
        if self._group.busy:
            self.hint.setText("上一项操作还在进行，请等它结束。")
            return False
        return self._group.start(workers.read_targets_worker, on_ok=self._applied,
                                 on_err=self._write_failed, label="read-targets")

    def _applied(self, data):
        self._rows = list(data.get("rows") or [])
        self._render()
        if self._on_changed is not None:
            self._on_changed(self._rows)
        errors = [r for r in self._rows if r.get("error")]
        if errors:
            names = "、".join(f"{r['name']}({r['error']})" for r in errors)
            self.hint.setText(f"部分目标读取失败：{names}")
            return
        active = [r for r in self._rows if r.get("value")]
        total, count = len(self._rows), len(active)
        self.hint.setText(f"共 {total} 个目标，其中 {count} 个已设置代理。" if active
                          else f"共 {total} 个目标，当前均未设置代理。")

    def _render(self):
        def status(row):
            if not row.get("available"):
                return ("未安装", "warning")
            return ("已启用", "success") if row.get("value") else ("未设置", "info")

        fill_table(
            self.table, self._rows,
            (("name", None), ("value", lambda v, _r: v or _EMPTY),
             (None, None), ("note", None), (None, None)),
            chips={2: status},
            action_col=4,
            actions=(("设为当前", lambda r: (ACT_SET, r["id"])),
                     ("清除", lambda r: (ACT_UNSET, r["id"]))),
            action_handler=self._on_row_action)

    # ── 写（单目标）──────────────────────────────────────────────
    def _on_row_action(self, payload):
        action, target_id = payload
        row = next((r for r in self._rows if r["id"] == target_id), None)
        if row is None:
            return
        if action == ACT_UNSET:
            if not confirm(self, "确认清除",
                           f"清除 {row['name']} 的代理设置？\n\n"
                           f"说明：{row['note']}\n\n"
                           f"环境变量类目标会从 HKCU\\Environment 删除并广播，"
                           f"新开的程序才会生效。", ok_text="清除"):
                return
            url = ""
        else:
            url = (self._url_provider() or "").strip()
            if not url:
                self.hint.setText("请先在顶部填入代理地址，再点「设为当前」。")
                notify(self, "缺少代理地址", "顶部地址框为空，无法写入。", error=True)
                return
            if not confirm(self, "确认设置",
                           f"把 {row['name']} 的代理设为\n{url}\n\n"
                           f"说明：{row['note']}\n\n确认写入？", ok_text="写入"):
                return
        self._dispatch(target_id, url, action)

    def _dispatch(self, target_id, url, action):
        if self._group.busy:
            self.hint.setText("上一项操作还在进行，请等它结束。")
            return False
        started = self._group.start(
            lambda ctx: workers.apply_target_worker(ctx, target_id, url, action),
            on_ok=self._write_applied, on_err=self._write_failed,
            label=f"{action}:{target_id}")
        if not started:
            self.hint.setText("任务未能启动（可能上一项还没结束）。")
        return started

    def _write_applied(self, data):
        result = data.get("result")
        msg = getattr(result, "message", "") or "（无消息）"
        detail = getattr(result, "detail", "") or ""
        ok = bool(result and result.ok)
        self.hint.setText(f"{data.get('name')}：{msg}"
                          + (f"（{detail}）" if detail else ""))
        notify(self, "已生效" if ok else "操作未成功",
               f"{data.get('name')}：{msg}" + (f"\n{detail}" if detail else ""),
               error=not ok)
        if self._on_changed is not None:
            self._on_changed()      # 读回最新值，顺带刷新首页快照

    def _write_failed(self, kind, text):
        self.hint.setText(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

    # ── 写（全部目标；页面顶部「一键启用/停用」调用）───────────
    def apply_all(self, action, url=""):
        """批量设/清全部目标。action ∈ {"set", "unset"}；返回是否已下发。"""
        if self._group.busy:
            self.hint.setText("上一项操作还在进行，请等它结束。")
            return False
        started = self._group.start(
            lambda ctx: workers.apply_all_worker(ctx, url, action),
            on_ok=self._applied_all, on_err=self._write_failed,
            label=f"all:{action}")
        if not started:
            self.hint.setText("任务未能启动（可能上一项还没结束）。")
        return started

    def _applied_all(self, data):
        text, ok = summarize([r.get("result")
                              for r in (data.get("results") or [])])
        self.hint.setText(text)
        notify(self, "已生效" if ok else "部分失败", text, error=not ok)
        if self._on_changed is not None:
            self._on_changed()      # 读回最新值，顺带刷新首页快照
