"""router_admin.widgets.tabs_config：配置编辑 Tab（/etc/config 白名单内的读/改/存）。

写操作全部有二次确认：保存（先备份再原子写回 + 回读校验）、重启服务（节名→服务名
走 `SECTION_SERVICE` **静态白名单映射**，不把节名拼进命令）、重启路由器（danger
按钮 + 双重确认，第二道必须键入 `reboot`）、删除备份（确认框）。备份「恢复」只把
内容灌回编辑区，仍需点保存才真正写路由器。

`find_dangerous_changes` 里 `level == "block"` 的项一律禁用保存按钮并红色列出。
后台任务函数（read_worker / save_worker / restart_worker / reboot_worker /
save_text）在 `workers.py`，本文件只管「渲染 + 确认 + 点线」。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_combo, make_label

from .. import backup, config_editor
from ..connection import CONFIG_WHITELIST, is_allowed_config
from ..workers import (read_worker, reboot_worker, restart_worker, save_worker)
from . import (add_chip, alert, confirm, confirm_phrase, make_chip_row,
               make_mono_editor, notify, reset_chips)
from .tables import BackupList

_, QtCore, QtGui, QtWidgets = import_qt()

#: 静态白名单：配置节名 → 生效所需重启的服务名（**不是**用户输入）
SECTION_SERVICE = {"network": "network", "firewall": "firewall",
                   "dnsmasq": "dnsmasq", "dhcp": "dnsmasq", "wireless": "network"}
REBOOT_PHRASE = "reboot"


def allowed_sections():
    """白名单内的配置节（is_allowed_config 过滤，杜绝白名单外的节）。"""
    return [s for s in CONFIG_WHITELIST if is_allowed_config(s)]


def save_text(section):
    """保存 /etc/config/<section> 的二次确认文案。"""
    return (f"即将把编辑区内容写入路由器的 /etc/config/{section}。\n\n"
            f"写入采用「同目录临时文件 + mv」原子替换；写入前会自动把当前配置备份到"
            f"本机，备份失败则中止，不会半写。\n\n"
            f"注意：保存后不会自动生效，还需点「重启服务」或「重启路由器」；"
            f"若改的是 network/wireless 且配置有误，路由器可能失联，"
            f"届时需走近设备用原配置恢复。\n\n确认写入？")


class ConfigTab(QtWidgets.QWidget):
    """配置编辑页。"""

    def __init__(self, owner, group, *, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._old_uci = {}
        self._old_text = ""
        self._issues = []
        sz = sizing()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(sz["dialog_spacing"])
        lay.addLayout(self._build_bar())
        self.editor = make_mono_editor(parent=self)
        lay.addWidget(self.editor, 1)
        row, self.chip_box, self.chip_lay = make_chip_row("校验", parent=self)
        lay.addLayout(row)
        self.backups = BackupList(self)
        self.backups.bind(backup)
        lay.addWidget(self.backups)
        self.status = make_label("先选配置节并点「读取」。", role="caption",
                                 parent=self)
        lay.addWidget(self.status)
        self.btn_save.setEnabled(False)

    def _build_bar(self):
        sz = sizing()
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sz["radius_sm"])
        row.addWidget(make_label("配置节", role="caption", parent=self))
        self.combo = make_combo(allowed_sections(), parent=self)
        self.combo.setMinimumWidth(sz["btn_min_width"])
        self.combo.currentTextChanged.connect(lambda _t: self._on_section())
        row.addWidget(self.combo)
        specs = (("读取", "read", self.refresh, "default"),
                 ("校验", "check", self._validate, "default"),
                 ("保存", "save", self._save, "primary"),
                 ("重启服务", "restart", self._restart, "default"),
                 ("重启路由器", "reboot", self._reboot, "danger"))
        for text, attr, slot, kind in specs:
            btn = make_button(text, kind=kind, size="sm", parent=self)
            btn.clicked.connect(slot)
            row.addWidget(btn)
            setattr(self, f"btn_{attr}", btn)
        row.addStretch(1)
        return row

    def _restore(self):
        """把选中的本机备份灌进编辑区（不写路由器，仍需保存）。"""
        content = self.backups.on_restore()
        if content is None:
            return
        self.editor.setPlainText(content)
        self._validate()
        self.status.setText("已把选中备份灌入编辑区（尚未写入路由器）。"
                            "核对无误后点「校验」→「保存」。")

    def section(self):
        return self.combo.currentText()

    def _on_section(self):
        self._old_uci, self._old_text, self._issues = {}, "", []
        self.editor.setPlainText("")
        reset_chips(self.chip_lay)
        self.btn_save.setEnabled(False)
        self.status.setText(f"已选 {self.section()}，点「读取」载入当前配置。")

    def refresh(self):
        if not self._group.start(read_worker(self.section()),
                                 on_ok=self.apply_result,
                                 on_err=self._read_failed,
                                 label=f"read {self.section()}"):
            notify(self, "无法读取", "尚未连接路由器或上一轮任务未结束。",
                   error=True)
            return False
        self.status.setText("读取中…")
        return True

    def _read_failed(self, kind, text):
        self.status.setText("读取失败")
        notify(self, "读取配置失败", text, error=True)

    def apply_result(self, data):
        """把远端文本规整成可回写的 UCI 文本，并留存改前基线。"""
        self._old_uci = config_editor.parse_uci(data.get("text") or "")
        self._old_text = config_editor.serialize_uci(self._old_uci)
        self.editor.setPlainText(self._old_text)
        self._validate()
        self.status.setText(
            f"已载入 /etc/config/{data.get('section')}"
            f"（{len(self._old_text.splitlines())} 行）。改完点「校验」。")

    def _validate(self):
        """比对改前改后 → 渲染风险胶囊 → block 级则禁用保存。"""
        if not self._old_text:
            self.status.setText("尚未读取配置，无法校验。")
            return []
        self._issues = config_editor.find_dangerous_changes(
            self.section(), self._old_uci,
            config_editor.parse_uci(self.editor.toPlainText()),
            current_lan_ip=self._owner.lan_ip)
        reset_chips(self.chip_lay)
        for issue in self._issues:
            blocked = issue.get("level") == "block"
            add_chip(self.chip_lay, f"{issue.get('key')}：{issue.get('reason')}",
                     "error" if blocked else "warning", parent=self.chip_box)
        self.btn_save.setEnabled(
            not config_editor.has_blocking_issue(self._issues))
        if self.btn_save.isEnabled():
            self.status.setText("校验通过（有告警），点「保存」会再确认一次。"
                                if self._issues else "校验通过，无风险项。")
        else:
            self.status.setText("存在阻断级风险，保存已禁用；请按上方理由修改后再试。")
        return self._issues

    def _save(self):
        issues = self._validate()
        if config_editor.has_blocking_issue(issues):
            alert(self, "存在阻断级风险",
                  "以下改动可能导致路由器失联，已禁止保存：\n\n"
                  + "\n".join(f"· {i.get('key')}：{i.get('reason')}"
                              for i in issues if i.get("level") == "block"))
            return
        section, content = self.section(), self.editor.toPlainText()
        if not confirm(self, "确认保存配置", save_text(section), ok_text="备份并写入"):
            return
        if not self._group.start(save_worker(section, content), on_ok=self._saved,
                                 on_err=self._write_failed, label=f"save {section}"):
            notify(self, "无法保存", "上一轮任务未结束，请稍候。", error=True)

    def _write_failed(self, kind, text):
        alert(self, "写入失败", f"配置没有被修改。原因：\n\n{text}")

    def _saved(self, data):
        if data.get("stage") == "backup":
            alert(self, "已中止写入", data.get("error", "备份失败"))
            return
        if not data.get("ok"):
            alert(self, "写入失败", f"路由器没有返回写入成功标记。\n"
                                    f"输出：{data.get('output')!r}\n"
                                    f"回读：{data.get('verified')!r}")
            return
        verified = (data.get("verified") or "").strip()
        self.backups.refresh()
        notify(self, "已保存",
               f"已写入 /etc/config/{self.section()}"
               + (f"，改前配置已备份到 {data['backup']}" if data.get("backup") else "")
               + "。\n回读首行："
               + (verified.splitlines()[0] if verified else "—")
               + "\n重启相关服务后生效。")
        self.refresh()

    def _restart(self):
        section = self.section()
        service = SECTION_SERVICE.get(section)
        if not service:
            notify(self, "无重启映射",
                   f"{section} 没有对应的可重启服务，改动需重启路由器后生效。")
            return
        text = (f"即将重启服务「{service}」使 /etc/config/{section} 的改动生效。\n\n"
                f"重启期间网络会短暂中断；若该服务配置有误，路由器可能失联。\n\n"
                f"确认重启？")
        if not confirm(self, "确认重启服务", text, ok_text=f"重启 {service}"):
            return
        if not self._group.start(restart_worker(service), on_ok=self._restart_done,
                                 on_err=self._write_failed, label="restart"):
            notify(self, "无法重启", "上一轮任务未结束，请稍候。", error=True)

    def _restart_done(self, data):
        notify(self, "已重启", f"服务「{data.get('service')}」已重启，配置改动已生效。")
        self.refresh()

    def _reboot(self):
        """双重确认：普通确认框 + 必须键入 `reboot` 的确认框。"""
        if not confirm(self, "第一重确认：重启路由器",
                       "即将重启整台路由器。\n\n重启后所有连接会断开，Wi-Fi 与 WAN "
                       "会重新协商（PPoE 拨号约需 1 分钟）。\n\n确认继续？",
                       ok_text="继续"):
            return
        if not confirm_phrase(
                self, "第二重确认：键入 reboot",
                "这是不可撤销的操作，且会立即切断本机与路由器的一切连接。\n"
                "若当前通过无线接入，重启后无线会自动恢复。\n\n"
                f"请键入 {REBOOT_PHRASE} 以确认。", REBOOT_PHRASE):
            return
        if not self._group.start(reboot_worker(), on_ok=self._rebooted,
                                 on_err=self._write_failed, label="reboot"):
            notify(self, "无法重启", "上一轮任务未结束，请稍候。", error=True)

    def _rebooted(self, data):
        notify(self, "已下发重启", data.get("note", "路由器正在重启。"))
        self._owner.mark_offline()
