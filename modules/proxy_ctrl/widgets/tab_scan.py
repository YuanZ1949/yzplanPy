"""proxy_ctrl.widgets.tab_scan：局域网代理扫描（菜单 1 / 2 / 11）。

移植自 toggle_proxy 的「默认扫描」「自定义扫描」「保存结果」。扫描是纯逻辑层
`scanner.scan()` 的薄壳：参数收集 → 后台线程 → 进度条 → 结果表 → 落盘。

**「包含本机」默认勾选**：原版 `scanner_new.ps1` 不排除任何保留段，而用户最常见
的诉求就是找出**本机**自跑的 Clash（默认 7890 端口）。`scanner.scan` 的
`exclude_self` 默认为 True（保持纯逻辑层既有契约），本 Tab 用勾选框反传。

**0 结果必须给明确提示**：`generate_204` 在部分网络下不可达，届时所有候选都会被
判为非代理（返回 200/超时），表格空是正常结果而非故障，文案里要写清楚。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import (make_button, make_checkbox, make_label, make_line_edit)

from .. import scanner, workers
from . import make_card_block, make_usage_bar, notify
from .tables import clear_table, fill_table, make_table

_, QtCore, QtGui, QtWidgets = import_qt()

#: 结果表头列序
HEADERS = ("IP", "端口", "延迟", "评级", "类型", "操作")
#: TCP 探测超时默认值（秒）
DEFAULT_TIMEOUT = 1.0
#: 阶段一并发默认值
DEFAULT_MAX_WORKERS = 150
#: 阶段二（验证）并发默认值
DEFAULT_VERIFY_WORKERS = 20
#: 0 结果时的排查提示
EMPTY_HINT = ("未找到可用代理。若确认本机开着代理程序，常见原因："
              "① 代理端口不在列表里；② generate_204 目标在当前网络不可达"
              "（此时所有候选都会被判为非代理）。")


class ScanTab(QtWidgets.QWidget):
    """局域网扫描。`start_scan()` 下发扫描；`use_candidate()` 把某行写进地址栏。"""

    def __init__(self, owner, group, *, parent=None, on_use=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._on_use = on_use
        self._last = None                      # 最近一次扫描结果，供「用此代理」取用
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_params())
        root.addWidget(self._build_results(), 1)

    # ── 参数区 ──────────────────────────────────────────────────
    def _build_params(self):
        card, lay = make_card_block("扫描参数", parent=self)
        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(sizing()["radius_sm"])
        self.edit_subnet = make_line_edit("网段，如 192.168.2.0/24", parent=card)
        self.edit_subnet.setText(scanner.DEFAULT_SUBNET)
        self.edit_ports = make_line_edit("端口，逗号或空格分隔，支持 1080-1085",
                                         parent=card)
        self.edit_ports.setText(" ".join(str(p) for p in scanner.DEFAULT_PORTS))
        for text, widget in (("网段", self.edit_subnet), ("端口", self.edit_ports)):
            row1.addWidget(make_label(text, role="caption", parent=card))
            row1.addWidget(widget)
        row1.addStretch(1)
        lay.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(sizing()["radius_sm"])
        self.edit_timeout = make_line_edit("超时秒", parent=card)
        self.edit_timeout.setText(str(DEFAULT_TIMEOUT))
        self.edit_workers = make_line_edit("并发", parent=card)
        self.edit_workers.setText(str(DEFAULT_MAX_WORKERS))
        self.chk_self = make_checkbox("包含本机", parent=card)
        self.chk_self.setChecked(True)          # 用户最常要找本机自跑的 Clash
        for text, widget in (("TCP超时", self.edit_timeout),
                             ("并发", self.edit_workers)):
            row2.addWidget(make_label(text, role="caption", parent=card))
            row2.addWidget(widget)
        row2.addWidget(self.chk_self)
        row2.addStretch(1)
        self.btn_scan = make_button("开始扫描", kind="primary", parent=card)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop = make_button("停止", kind="danger", parent=card)
        self.btn_stop.clicked.connect(self.stop_scan)
        self.btn_stop.setEnabled(False)
        row2.addWidget(self.btn_scan)
        row2.addWidget(self.btn_stop)
        lay.addLayout(row2)

        self.bar = make_usage_bar(parent=card)
        lay.addWidget(self.bar)
        self.hint = make_label("扫描只在私有网段内进行；确认时必须精确返回 "
                               f"HTTP {scanner.EXPECTED_STATUS} 才算真代理。",
                               role="caption", parent=card)
        lay.addWidget(self.hint)
        return card

    # ── 结果区 ──────────────────────────────────────────────────
    def _build_results(self):
        card, lay = make_card_block(None, parent=self)
        self.title = make_label("扫描结果", role="caption", parent=card)
        lay.addWidget(self.title)
        self.table = make_table(HEADERS, parent=card)
        lay.addWidget(self.table)
        return card

    def _params(self):
        """读输入 → 校验。失败抛 ValueError（由 start_scan 就地提示）。"""
        subnet = (self.edit_subnet.text() or "").strip() or scanner.DEFAULT_SUBNET
        port_spec = (self.edit_ports.text() or "").strip()
        if not scanner.is_private_network(subnet):
            raise ValueError(f"网段不在私有段内：{subnet}")
        if not scanner.parse_port_range(
                port_spec or " ".join(str(p) for p in scanner.DEFAULT_PORTS))[0]:
            raise ValueError("端口列表为空或全部非法")
        return {
            "subnet": subnet,
            "port_spec": port_spec,
            "timeout": max(0.2, float(self.edit_timeout.text() or DEFAULT_TIMEOUT)),
            "max_workers": max(1, int(self.edit_workers.text() or DEFAULT_MAX_WORKERS)),
        }

    # ── 扫描 ────────────────────────────────────────────────────
    def start_scan(self, *_args):
        """下发一次扫描。参数非法就地提示，不起线程。"""
        if self._group.busy:
            self.hint.setText("上一项任务还在跑（可能在扫描中），请等它结束。")
            return False
        try:
            params = self._params()
        except (ValueError, TypeError) as exc:
            self.hint.setText(f"参数不合法：{exc}")
            notify(self, "参数不合法", str(exc), error=True)
            return False
        self.bar.set_percent(0, "扫描中…")
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.hint.setText(f"正在扫描 {params['subnet']}…")
        ok = self._group.start(
            lambda ctx: workers.scan_worker(
                ctx, include_self=self.chk_self.isChecked(), **params),
            on_ok=self._applied, on_err=self._failed, on_progress=self._on_progress,
            label="scan")
        if not ok:
            self._reset_buttons()
            self.hint.setText("扫描任务未能启动。")
        return ok

    def stop_scan(self, *_args):
        """请求中断。中断是「部分结果」，仍会渲染并落盘。"""
        self._group.cancel()
        self.hint.setText("正在停止（当前批次跑完后生效）…")
        return True

    def _on_progress(self, done, total=1.0):
        """scanner 约定 total 恒为 1.0、done ∈ [0,1]。"""
        try:
            value = max(0.0, min(1.0, float(done) / (float(total) or 1.0)))
        except (TypeError, ValueError, ZeroDivisionError):
            value = 0.0
        self.bar.set_percent(value * 100, f"扫描中 {value * 100:.0f}%")

    def _applied(self, data):
        self._reset_buttons()
        self._last = data
        results = list(data.get("results") or [])
        self._render(results)
        warnings = data.get("warnings") or []
        if data.get("cancelled"):
            self.hint.setText("已手动停止，下面是停止前的部分结果。")
        elif not results:
            self.hint.setText(EMPTY_HINT)
        else:
            self.hint.setText(f"找到 {len(results)} 个可用代理，"
                              f"已按延迟升序排列；点击「用此」把它填入顶部地址栏。")
        for text in warnings[:3]:               # 只提示前 3 条，避免刷屏
            notify(self, "端口解析提示", text, error=True)
        self._persist(data, results)

    def _failed(self, kind, text):
        self._reset_buttons()
        self.bar.set_percent(0, "—")
        self.hint.setText(text.replace("\n", " "))
        notify(self, "扫描失败", text, error=True)

    def _reset_buttons(self):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _render(self, results):
        clear_table(self.table)
        rows = [{"ip": r.ip, "port": r.port, "ms": r.latency_ms,
                 "kind": r.kind, "url": f"http://{r.ip}:{r.port}"} for r in results]
        fill_table(
            self.table, rows,
            (("ip", None), ("port", None), ("ms", lambda v, _r: f"{v} ms"),
             (None, None), ("kind", None), (None, None)),
            numeric={1, 2},
            chips={3: lambda r: (scanner.rate_latency(r["ms"]), _latency_kind(r["ms"]))},
            action_col=5,
            actions=(("用此", lambda r: r["url"]),),
            action_handler=self._on_use_row)
        self.title.setText(f"扫描结果（{len(rows)} 个）")

    def _on_use_row(self, url):
        if self._on_use is not None:
            self._on_use(url)

    def _persist(self, data, results):
        """把本次扫描落盘。失败只提示，不影响表格里的结果。"""
        if not results and not data.get("cancelled"):
            return
        workers.save_scan_worker(None, data.get("subnet"), results,
                                 data.get("timestamp"))


def _latency_kind(ms):
    """延迟 → chip 颜色档位（与 scanner.rate_latency 的三档阈值一致）。"""
    return "success" if ms < 100 else ("info" if ms < 300 else "warning")
