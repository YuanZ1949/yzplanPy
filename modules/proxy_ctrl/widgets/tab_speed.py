"""proxy_ctrl.widgets.tab_speed：代理测速（菜单 12）+ 扫描历史（菜单 11）。

移植自 toggle_proxy 的 `speed_test.ps1`：经代理连打 `generate_204` 五轮，取成功
轮次平均延迟并四档评级。`scanner` 与 `speedtest` 已经把「只算 2xx」「全失败给三条
排查建议」做在纯逻辑层，本 Tab 只负责收参数、发后台任务、渲染结论。

历史区读 `store.scan_history()`（本机 JSON，不联网），可导出到
`store.EXPORT_DIR` 或清空。导出走后台任务，避免大历史卡住主线程。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label, make_line_edit, make_status_chip

from .. import store, workers
from . import confirm, make_card_block, notify
from .tables import clear_table, fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

#: 默认测速轮数（原版 5 轮）
DEFAULT_ROUNDS = 5
#: 历史表头列序
HISTORY_HEADERS = ("时间", "网段", "可用代理数")


class SpeedTab(QtWidgets.QWidget):
    """测速 + 历史。`test()` 对 url 发起测速；`refresh_history()` 重画历史表。"""

    def __init__(self, owner, group, *, parent=None, url_provider=None,
                 on_use=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._url_provider = url_provider or (lambda: "")
        self._on_use = on_use
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_speed())
        root.addWidget(self._build_history(), 1)

    # ── 测速区 ──────────────────────────────────────────────────
    def _build_speed(self):
        card, lay = make_card_block("代理测速", parent=self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        self.edit_url = make_line_edit("代理地址，如 http://192.168.2.10:7890",
                                       parent=card)
        self.edit_rounds = make_line_edit("轮数", parent=card)
        self.edit_rounds.setText(str(DEFAULT_ROUNDS))
        self.edit_rounds.setMaximumWidth(sizing()["btn_min_width"])
        row.addWidget(make_label("地址", role="caption", parent=card))
        row.addWidget(self.edit_url, 1)
        row.addWidget(make_label("轮数", role="caption", parent=card))
        row.addWidget(self.edit_rounds)
        self.btn_test = make_button("开始测速", kind="primary", parent=card)
        self.btn_test.clicked.connect(self.test)
        row.addWidget(self.btn_test)
        lay.addLayout(row)

        result = QtWidgets.QHBoxLayout()
        result.setSpacing(sizing()["radius_sm"])
        result.addWidget(make_label("结论", role="caption", parent=card))
        self.chip = make_status_chip("未测速", kind="info", parent=card)
        result.addWidget(self.chip)
        self.lb_avg = make_label("", role="body", parent=card)
        result.addWidget(self.lb_avg)
        result.addStretch(1)
        lay.addLayout(result)

        self.lb_samples = make_label("", role="caption", parent=card)
        lay.addWidget(self.lb_samples)
        self.hint = make_label(
            "测速目标为 generate_204；留空地址表示「当前未设代理」，"
            "不做代理直接请求（属正常情况，不判失败）。",
            role="caption", parent=card)
        lay.addWidget(self.hint)
        return card

    def test(self, url=None, *_args):
        """对 url（或顶部地址框内容）发起测速。返回是否已下发。"""
        if self._group.busy:
            self.hint.setText("上一项任务还在跑，请等它结束。")
            return False
        target = (url if url is not None else (self._url_provider() or "")).strip()
        try:
            rounds = max(1, int(self.edit_rounds.text() or DEFAULT_ROUNDS))
        except (TypeError, ValueError):
            rounds = DEFAULT_ROUNDS
        self.btn_test.setEnabled(False)
        self.chip.setText("测速中…")
        self.hint.setText(f"正在测速 {target or '（无代理）'} …")
        ok = self._group.start(
            lambda ctx: workers.speed_worker(ctx, target, rounds),
            on_ok=self._applied, on_err=self._failed, label="speed")
        if not ok:
            self.btn_test.setEnabled(True)
            self.hint.setText("测速任务未能启动。")
        return ok

    def _applied(self, result):
        self.btn_test.setEnabled(True)
        self.chip.setText(result.rating or "—")
        self.chip.setStyleSheet("")            # 清掉可能的旧分档 QSS
        if result.samples:
            self.lb_avg.setText(f"平均 {result.avg_ms} ms"
                                f"（成功 {len(result.samples)} 轮）")
            self.lb_samples.setText("各轮耗时：" +
                                    "、".join(f"{s}ms" for s in result.samples))
        else:
            self.lb_avg.setText("平均 — ms（无成功轮次）")
            self.lb_samples.setText("")
        hints = list(result.hints or [])
        self.hint.setText(hints[0] if hints else
                          f"测速完成：{result.rating}。")
        for text in hints[1:]:
            notify(self, "排查建议", text, duration=6000)

    def _failed(self, kind, text):
        self.btn_test.setEnabled(True)
        self.chip.setText("测速失败")
        self.hint.setText(text.replace("\n", " "))
        notify(self, "测速失败", text, error=True)

    # ── 历史区 ──────────────────────────────────────────────────
    def _build_history(self):
        card, lay = make_card_block(None, parent=self)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(sizing()["radius_sm"])
        self.title = make_label("扫描历史", role="caption", parent=card)
        bar.addWidget(self.title)
        bar.addStretch(1)
        self.btn_export = make_button("导出", parent=card)
        self.btn_export.clicked.connect(self.export_history)
        self.btn_clear = make_button("清空", kind="danger", parent=card)
        self.btn_clear.clicked.connect(self.clear_history)
        bar.addWidget(self.btn_export)
        bar.addWidget(self.btn_clear)
        lay.addLayout(bar)
        self.table = make_table(HISTORY_HEADERS, parent=card)
        lay.addWidget(self.table)
        return card

    def refresh_history(self):
        """重画历史表。纯本地读文件，不联网、不同步起线程。"""
        items = store.scan_history()
        clear_table(self.table)
        fill_table(
            self.table,
            [{"ts": it.get("ts"), "subnet": it.get("subnet"),
              "count": len(it.get("results") or [])} for it in items],
            (("ts", None), ("subnet", None),
             ("count", lambda v, _r: f"{v} 个")),
            numeric={2})
        self.title.setText(f"扫描历史（最近 {store.MAX_SCANS} 次，"
                           f"当前 {len(items)} 次）")

    def export_history(self, *_args):
        """导出到 EXPORT_DIR。空历史直接拦下，不必起线程。"""
        if not store.scan_history():
            notify(self, "没有可导出的记录", "先扫描一次再导出。", error=True)
            return False
        path = store.export_to_disk()
        if path:
            notify(self, "已导出", f"扫描历史已写入：\n{path}")
        else:
            notify(self, "导出失败", "无法写入导出目录，请检查权限。", error=True)
        return bool(path)

    def clear_history(self, *_args):
        if not store.scan_history():
            notify(self, "历史本来就是空的", "无需清空。")
            return False
        if not confirm(self, "确认清空历史",
                       "即将清空全部扫描历史（记忆的代理地址会保留）。\n\n"
                       "清空后无法恢复，确认继续？", ok_text="清空"):
            return False
        store.clear_history()
        self.refresh_history()
        notify(self, "已清空", "扫描历史已清空。")
        return True
