"""router_admin.widgets.tabs_wan：宽带账号 Tab（在线状态 + 账号表单 + 独立重拨）。

与「配置编辑」Tab 的分工：配置编辑是**通用 UCI 文本框**，口令类字段一律被
`config_editor.SECRET_KEY_PARTS` 拦成 block（刻意如此，防止顺手改坏密钥）；宽带
账号是**唯一正当入口**，走「已授权 + 窄校验 + 备份 + 原子写 + 回读」这条同样严格
但不放行的管道。两条写路径共用 `workers.backup_then_write`，安全属性不会各自漂移。

**口令绝不进 UI**：`wan.parse_account` 只回 `has_password` 布尔；口令框永远留空，
留空 = 不修改（与本模块自身的 telnet 口令框同一套约定）。保存成功后提示「需要
重拨才生效」，重拨是**独立按钮**，不自动触发——拨号失败不该被当成保存失败。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label, make_line_edit

from .. import wan
from ..workers_wan import (wan_account_worker, wan_log_worker,
                           wan_redial_worker, wan_save_worker,
                           wan_status_worker)
from . import (add_chip, alert, confirm, make_card_block, make_chip_row,
               make_mono_editor, make_password_edit, make_stat_card, notify,
               reset_chips)

_, QtCore, QtGui, QtWidgets = import_qt()

#: 状态指标小卡（标题, `wan.parse_status` 的键）——一对一，不另造字段名
CARDS = (("协议", "proto"), ("IPv4", "ipv4"), ("IPv6", "ipv6"),
         ("在线时长", "uptime_s"), ("物理口", "device"), ("链路", "l3_device"))

#: 拨号日志区展示的最大行数（重拨输出可能很长，界面只看尾部）
LOG_TAIL_LINES = 12


class WanTab(QtWidgets.QWidget):
    """宽带账号页。"""

    def __init__(self, owner, group, *, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._account = {}
        self._polls = 0
        self._timer = None
        sz = sizing()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sz["dialog_spacing"])
        lay.addWidget(self._build_status_card())
        lay.addWidget(self._build_account_card())
        self.status = make_label("先点「读取状态」与「读取账号」。", role="caption",
                                 parent=self)
        lay.addWidget(self.status)

    # ── 构建 ──────────────────────────────────────────────────────
    def _bar(self, card, *buttons):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        for btn in buttons:
            row.addWidget(btn)
        row.addStretch(1)
        return row

    def _build_status_card(self):
        card, lay = make_card_block("宽带状态", parent=self)
        self.btn_status = make_button("读取状态", kind="ghost", size="sm",
                                      parent=self)
        self.btn_status.clicked.connect(self.read_status)
        self.btn_redial = make_button("重新拨号", kind="primary", size="sm",
                                      parent=self)
        self.btn_redial.clicked.connect(self._redial)
        self.btn_log = make_button("拨号日志", kind="ghost", size="sm",
                                   parent=self)
        self.btn_log.clicked.connect(self._read_log)
        lay.addLayout(self._bar(card, self.btn_status, self.btn_redial,
                                self.btn_log))
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(sizing()["radius_sm"])
        self._cards = {}
        for row, (title, key) in enumerate(CARDS):
            one, value = make_stat_card(title, parent=card)
            self._cards[key] = value
            grid.addWidget(one, row // 3, row % 3)
        lay.addLayout(grid)
        row, self.chip_box, self.chip_lay = make_chip_row("", parent=card)
        lay.addLayout(row)
        self.log_view = make_mono_editor(parent=card, read_only=True)
        self.log_view.setVisible(False)
        lay.addWidget(self.log_view)
        return card

    def _build_account_card(self):
        card, lay = make_card_block("宽带账号（PPPoE）", parent=self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label("账号", role="caption", parent=card))
        self.edit_user = make_line_edit("宽带账号", parent=card)
        row.addWidget(self.edit_user, 1)
        row.addWidget(make_label("口令", role="caption", parent=card))
        self.edit_pass = make_password_edit("留空 = 不修改口令", parent=card)
        row.addWidget(self.edit_pass, 1)
        lay.addLayout(row)
        self.btn_account = make_button("读取账号", kind="ghost", size="sm",
                                       parent=card)
        self.btn_account.clicked.connect(self.read_account)
        self.btn_save = make_button("保存账号", kind="default", size="sm",
                                    parent=card)
        self.btn_save.clicked.connect(self._save)
        lay.addLayout(self._bar(card, self.btn_account, self.btn_save))
        self.info = make_label("", role="caption", parent=card)
        lay.addWidget(self.info)
        return card

    # ── 渲染 ──────────────────────────────────────────────────────
    def _apply_status(self, status):
        """刷状态（`parse_status` 的结果里本来就没有口令，天然安全）。"""
        state = status or {}
        for _title, key in CARDS:
            value = self._cards[key]
            if key == "uptime_s":
                text = (wan.format_uptime(state.get("uptime_s"))
                        if state.get("uptime_s") else "—")
            else:
                text = state.get(key) or "—"
            value.setText(str(text))
        reset_chips(self.chip_lay)
        if state.get("error"):
            add_chip(self.chip_lay, f"未知：{state['error']}", "warning",
                     parent=self.chip_box)
            return
        up = bool(state.get("up"))
        add_chip(self.chip_lay, "在线" if up else "离线",
                 "success" if up else "error", parent=self.chip_box)
        if up and state.get("uptime_s"):
            add_chip(self.chip_lay, wan.format_uptime(state["uptime_s"]),
                     "info", parent=self.chip_box)
        if state.get("dns"):
            add_chip(self.chip_lay, f"DNS {state['dns'][0]}", "info",
                     parent=self.chip_box)

    def _apply_account(self, account):
        """回填账号。**只回填用户名**；口令框保持留空（留空 = 不修改）。"""
        data = account or {}
        self._account = dict(data)
        if data.get("username"):
            self.edit_user.setText(data["username"])
        self.info.setText(
            f"当前协议 {data.get('proto') or '—'}，物理口 {data.get('ifname') or '—'}，"
            f"MTU {data.get('mtu') or '—'}，IPv6 {data.get('ipv6') or '—'}；"
            + ("口令已设置（不回显）。" if data.get("has_password")
               else "尚未设置口令。"))

    def _collect(self):
        """(账号, 口令)——口令留空翻译成 `None`（= 不修改），不是空串。"""
        return self.edit_user.text().strip(), (self.edit_pass.text() or None)

    def _set_busy(self, busy):
        for btn in (self.btn_status, self.btn_redial, self.btn_log,
                    self.btn_account, self.btn_save):
            btn.setEnabled(not busy)

    def _start(self, worker, *, on_ok, label):
        if not self._group.start(worker, on_ok=on_ok, label=label):
            notify(self, "无法执行", "尚未连接路由器或上一轮任务未结束。", error=True)
            return False
        self._set_busy(True)
        return True

    def _fail(self, what):
        self._set_busy(False)
        self.status.setText(f"{what}失败")
        alert(self, f"{what}失败", "请确认已连接路由器后重试。")

    # ── 读取 ──────────────────────────────────────────────────────
    def read_status(self):
        self.status.setText("读取宽带状态中…")
        if not self._start(wan_status_worker(), on_ok=self._status_ok,
                           label="wan status"):
            self.status.setText("尚未连接路由器。")

    def _status_ok(self, data):
        self._set_busy(False)
        state = (data or {}).get("status") or {}
        self._apply_status(state)
        self.status.setText(wan.describe_status(state))

    def read_account(self):
        self.status.setText("读取宽带账号中…")
        if not self._start(wan_account_worker(), on_ok=self._account_ok,
                           label="wan account"):
            self.status.setText("尚未连接路由器。")

    def _account_ok(self, data):
        self._set_busy(False)
        if not (data or {}).get("present"):
            self.status.setText("/etc/config/network 里没有 interface 'wan' 段。")
            alert(self, "未找到宽带账号",
                  "/etc/config/network 里没有 config interface 'wan' 段。\n\n"
                  "这台路由器可能使用 DHCP 上联或桥接模式，宽带账号不在本机配置里。")
            return
        self._apply_account(data)
        self.status.setText("已读取宽带账号（口令不回显，留空即不修改）。")

    # ── 保存账号 ──────────────────────────────────────────────────
    def _save(self):
        username, password = self._collect()
        try:
            username = wan.validate_username(username)
            if password is not None:
                password = wan.validate_password(password)
        except wan.WanError as exc:
            alert(self, "账号格式不合法", str(exc))
            return
        if not confirm(self, "确认保存宽带账号",
                       wan.save_confirm_text(username,
                                             changing_password=password is not None),
                       ok_text="备份并写入"):
            return
        self.status.setText("正在备份并写入宽带账号…")
        if not self._start(wan_save_worker(username, password), on_ok=self._saved,
                           label="wan save"):
            self.status.setText("尚未连接路由器。")

    def _saved(self, data):
        self._set_busy(False)
        got = data or {}
        if not got.get("ok"):
            alert(self, "未写入", got.get("error") or "路由器没有返回写入成功标记。")
            self.status.setText("宽带账号未改动。")
            return
        self.edit_pass.clear()
        self.log_view.clear()
        self.log_view.setVisible(False)
        self.status.setText("宽带账号已写入，还需点「重新拨号」才会生效。")
        notify(self, "宽带账号已保存",
               "已写入 /etc/config/network"
               + (f"，改前配置已备份到 {got['backup']}" if got.get("backup") else "")
               + "。\n配置不会自动生效，请点「重新拨号」。")
        self.read_account()

    # ── 重拨 ──────────────────────────────────────────────────────
    def _redial(self):
        if not confirm(self, "确认重新拨号",
                       wan.redial_confirm_text(wan.DEFAULT_IFACE),
                       ok_text="重新拨号"):
            return
        self.status.setText("正在下发重拨…")
        if not self._start(wan_redial_worker(), on_ok=self._redial_ok,
                           label="wan redial"):
            self.status.setText("尚未连接路由器。")

    def _redial_ok(self, data):
        if not (data or {}).get("sent"):
            self._fail("重拨下发")
            self.status.setText("重拨命令未送达路由器，请确认连接后重试。")
            return
        self._set_busy(False)
        self.status.setText("重拨已下发，正在等待拨号完成…")
        self._polls = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(wan.REDIAL_POLL_MS)

    def _poll(self):
        """轮询宽带状态。**最多 `REDIAL_POLL_TIMES` 次**，避免界面永远转圈。"""
        self._polls += 1
        self._set_busy(False)
        if self._polls >= wan.REDIAL_POLL_TIMES:
            self._stop_timer()
            self.status.setText("轮询结束，点「读取状态」看最终结果。")
        else:
            self.status.setText(
                f"等待拨号…（第 {self._polls}/{wan.REDIAL_POLL_TIMES} 次）")
        self.read_status()

    def _stop_timer(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def _read_log(self):
        """读拨号日志。重拨是分离执行的，日志可能此刻还在写，读到什么算什么。"""
        if not self._start(wan_log_worker(), on_ok=self._log_ok, label="wan log"):
            return

    def _log_ok(self, data):
        self._set_busy(False)
        raw = (data or {}).get("raw") or ""
        self.log_view.setVisible(True)
        if not raw:
            self.log_view.setPlainText("（还没有拨号日志：没重拨过，或已被覆盖）")
            self.status.setText("没有拨号日志。")
            return
        self.log_view.setPlainText("\n".join(raw.splitlines()[-LOG_TAIL_LINES:]))
        self.status.setText(f"已读取拨号日志（末尾 {LOG_TAIL_LINES} 行以内）。")
