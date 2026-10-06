r"""right_menu.widgets.page_tabs.settings_tab：YZplan 右键子菜单开关、一键还原、备份快照。

三块卡：**YZplan 右键**（主开关 + 动作多选 + 「应用动作」）、**一键还原**（事前过一遍
`RestoreDialog` 预览 + 「打开数据目录」）、**备份**（快照表 + 「立即备份」）。本页是最后一个真标签，
装配层至此不再有占位。本 Tab 是 `yzmenu` 与 `store_restore` 两个纯逻辑层的薄壳。

**读同步、写异步**：`refresh()` 只读本地 JSON / 目录，外加一次 HKCU 取值（`get_yzmenu_state` 只读
`*` 根的三个特征值，`Win32Backend` 永不抛），全是毫秒级，为它们起 QThread 只会多一层悬挂线程风险
（与 `classic_tab` / `custom_tab` 同一判断），故同步读且**构造尾就调一次**；安装 / 卸载 / 一键还原一律经
`workers.TaskGroup`（要落注册表与账本，还原还要走提权作业并等回读）。**模块一律调用时取属性**
（`yzmenu.uninstall_yzmenu` / `rm_store.backup_snapshot`），否则 monkeypatch 拦不到。

**`confirm_fn` 是可测性缝**：预览对话框是模态的，离屏测试里会挂起，故 `restore_all` 开注入参数；
`apply_yzmenu` 是无模态操作（结果用非阻塞 notify），不需要缝。预览在起线程**之前**弹——「先看清楚再动手」
的顺序就是它存在的理由。

**写后补刷推迟到 idle**：`on_ok` 跑在 settled **之前**（此刻 group 仍 busy，立刻 `refresh` 会被守卫拒
掉），故成功只置 `_pending_refresh`，刷新由 owner 接的 `on_idle()` 执行。页面是 backend 的单一来源
（一律靠 `backend=` 注入）。表头 / 文案 / 快照文件名拆解 / 勾选 ⇄ 动作清单换算 / 返回值视图全在同包
`settings_rows.py`（Qt-free，可直接断言），本文件只管控件与线程接线。
"""
import os

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_checkbox, make_label

from ... import store as rm_store, workers, yzmenu
from ...registry_backend import Win32Backend
from .. import make_card_block, notify
from ..restore_dialog import RestoreDialog
from ..tables import fill_table, make_table
from . import settings_rows as rows

_, QtCore, QtGui, QtWidgets = import_qt()


class SettingsTab(QtWidgets.QWidget):
    """YZplan 右键子菜单的开关与动作选择、一键还原、备份快照。"""

    def __init__(self, owner, group, *, parent=None, page=None, backend=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._page = page
        self._backend = backend if backend is not None else Win32Backend()
        self._pending_refresh = False
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_yzmenu())
        root.addWidget(self._build_restore())
        root.addWidget(self._build_backup(), 1)
        self.hint = make_label(rows.HINT_IDLE, role="caption", parent=self)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.refresh()               # 构造尾同步渲染：本地 JSON + 一次 HKCU 取值（见 docstring）

    def _build_yzmenu(self):
        card, lay = make_card_block("YZplan 右键", parent=self)
        self.check_yzmenu = make_checkbox("在系统右键显示 YZplan 子菜单", parent=card)
        lay.addWidget(self.check_yzmenu)
        self.list_actions = []
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(sizing()["radius_sm"])
        for index, action in enumerate(yzmenu.ACTIONS):     # 顺序即菜单顺序，不另排序
            box = make_checkbox(yzmenu.ACTION_LABELS[action], parent=card)
            box.setChecked(True)          # 缺省全选（见 settings_rows.checked_by_state）
            self.list_actions.append(box)
            grid.addWidget(box, index // 2, index % 2)
        grid.setColumnStretch(grid.columnCount(), 1)          # 余量全给最后一列
        lay.addLayout(grid)
        self.btn_apply = make_button("应用动作", kind="primary", parent=card)
        self.btn_apply.clicked.connect(lambda: self.apply_yzmenu())
        lay.addLayout(self._row(self.btn_apply))
        return card

    def _build_restore(self):
        card, lay = make_card_block("一键还原", parent=self)
        for text in (rows.NOTE_RESTORE, rows.NOTE_CLASSIC):
            note = make_label(text, role="caption", parent=card)
            note.setWordWrap(True)
            lay.addWidget(note)
        self.btn_restore = make_button("一键还原", kind="danger", parent=card)
        self.btn_restore.clicked.connect(lambda: self.restore_all())
        self.btn_data_dir = make_button("打开数据目录", parent=card)
        self.btn_data_dir.clicked.connect(lambda: self.open_data_dir())
        lay.addLayout(self._row(self.btn_restore, self.btn_data_dir))
        return card

    def _build_backup(self):
        card, lay = make_card_block(rows.BACKUP_CARD_TITLE, parent=self)
        self.btn_backup = make_button("立即备份", parent=card)
        self.btn_backup.clicked.connect(lambda: self.export_backup())
        self.title = make_label("快照", role="caption", parent=card)
        lay.addLayout(self._row(self.btn_backup, self.title))
        self.table_backups = make_table(rows.HEADERS, parent=card)
        lay.addWidget(self.table_backups)
        return card

    def _row(self, *widgets):
        """三块卡共用的按钮行：左对齐 + 尾部 stretch（余量归卡片右边）。"""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return row

    # ── 同步读 + 渲染 ────────────────────────────────────────────
    def refresh(self, *_args):
        """同步重读 yzmenu 安装态与备份目录（不起线程）→ 返回快照条数。"""
        self._apply_yzmenu_state(yzmenu.get_yzmenu_state(self._backend))
        return self._render_backups()

    def _apply_yzmenu_state(self, state):
        """`{"installed", "actions"}` → 主开关 + 动作勾选；返回 installed。"""
        state = state if isinstance(state, dict) else {}
        installed = bool(state.get("installed"))
        self.check_yzmenu.setChecked(installed)
        # 勾选交给 rows.checked_by_state——**未安装时它一律返回全勾**，否则会装出空壳菜单。
        for box, on in zip(self.list_actions, rows.checked_by_state(
                yzmenu.ACTIONS, installed, state.get("actions"))):
            box.setChecked(on)
        return installed

    def _render_backups(self):
        """整表重填备份快照（行 = `BACKUP_DIR` 下的 `*.json`）→ 返回行数。

        `os.listdir` 必须 try/except：目录可能不存在（首次运行、或用户清过），那不是错误。"""
        try:
            names = os.listdir(rm_store.BACKUP_DIR)
        except (OSError, ValueError):
            names = []
        backup = rows.backup_rows(names, rm_store.BACKUP_DIR)
        fill_table(self.table_backups, backup, rows.BACKUP_COLUMNS,
                   action_col=rows.COL_ACTION, actions=rows.BACKUP_ACTIONS,
                   action_handler=lambda path: self._startfile(os.path.dirname(path)))
        self.title.setText(f"快照（{len(backup)} 份）")
        return len(backup)

    def open_data_dir(self):
        """打开账本所在目录（与 `page.open_data_dir` 同口径；`STATE_PATH` 调用时读）。"""
        return self._startfile(os.path.dirname(rm_store.STATE_PATH))

    def _startfile(self, target):
        """`os.startfile` 的统一出口：平台不支持 / 路径不存在都降级成一次非阻塞错误提示。"""
        try:
            os.startfile(target)                                  # noqa: S606
        except (OSError, AttributeError, ValueError):
            notify(self, "无法打开目录", "当前系统不支持 os.startfile。", error=True)
            return False
        return True

    # ── 写操作：子菜单开关 / 一键还原 / 备份 ─────────────────────
    def apply_yzmenu(self):
        """按主开关 + 动作勾选安装或卸载子菜单 → 起线程。group 忙返回 False。

        主开关关 → `uninstall`（**没有专用 worker**，`group.start` 包一层即可，模块属性调用时取、测试的
        monkeypatch 拦得到）；主开关开 → `yzmenu_install_worker`，动作清单就是当前勾选集（可能为空，
        交给 `yzmenu` 自己拒，见 `settings_rows.wanted_actions`）。"""
        if self._group.busy:
            self.hint.setText(rows.HINT_BUSY)
            return False
        if not self.check_yzmenu.isChecked():
            return self._start_write("yzmenu:uninstall",
                                     lambda ctx: yzmenu.uninstall_yzmenu(self._backend),
                                     rows.working_hint("uninstall"))
        wanted = rows.wanted_actions(yzmenu.ACTIONS,
                                     [box.isChecked() for box in self.list_actions])
        return self._start_write(
            "yzmenu:install",
            lambda ctx: workers.yzmenu_install_worker(ctx, self._backend, wanted),
            rows.working_hint("install", len(wanted)))

    def restore_all(self, *, confirm_fn=None):
        """把账本记下的每一类改动逐条撤销 → 确认后起线程。取消或 group 忙返回 False。"""
        if self._group.busy:
            self.hint.setText(rows.HINT_BUSY)
            return False
        ask = confirm_fn or self._default_restore_confirm
        if not ask():           # 真值判定，非 `is False`：注入缝返回 None/0/"" 一律当「取消」
            return False
        return self._start_write("settings:restore_all",
                                 lambda ctx: workers.restore_all_worker(ctx, self._backend),
                                 rows.working_hint("restore"))

    def _default_restore_confirm(self):
        """缺省确认路径：弹 `RestoreDialog` 预览。测试永远注入 `confirm_fn`，不进这里。"""
        dlg = RestoreDialog(self)
        try:
            return dlg.exec() == QtWidgets.QDialog.Accepted
        finally:
            dlg.deleteLater()          # 反复开关不能靠 parent 兜底释放（与编辑器同一口径）

    def export_backup(self):
        """立刻把当前账本快照进 `BACKUP_DIR` → 成功 True（非阻塞提示 + 刷新表）。`None` = 账本损坏
        （刻意不写「合法但空」的误导性快照）或目录不可写——不替用户猜。"""
        path = rm_store.backup_snapshot("manual")
        if not path:
            notify(self, "备份失败", "账本读不出或备份目录不可写。", error=True)
            self.hint.setText("备份失败：账本读不出或备份目录不可写。")
            return False
        name = os.path.basename(path)
        notify(self, "已备份", f"快照：{name}")
        self.hint.setText(f"已备份：{name}")
        self._render_backups()
        return True

    # ── 线程接线 / 状态与清理 ───────────────────────────────────
    def _start_write(self, label, fn, hint_text):
        """三个写动作的统一入口：起线程；按钮解禁交给 `on_idle`（忙则拒绝并提示）。"""
        started = self._group.start(fn, on_ok=self._on_write_ok,
                                    on_err=self._on_failed, label=label)
        if not started:
            self.hint.setText(rows.HINT_BUSY)
            return False
        self._set_buttons(False)
        self.hint.setText(hint_text)
        return True

    def _on_write_ok(self, result):
        """两个 worker 形状不同（`{"ok","report"}` vs `{"ok","detail"}`），按 report 分派视图；
        成功才置 `_pending_refresh`，刷新推迟到 `on_idle`（`on_ok` 跑在 settled **之前**）。"""
        view = rows.restore_view if rows.is_restore_result(result) else rows.result_view
        ok, title, body, hint = view(result)
        notify(self, title, body, error=not ok)
        self.hint.setText(hint)
        self._pending_refresh = ok

    def _on_failed(self, kind, text):
        self._set_buttons(True)
        self.hint.setText(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

    def _set_buttons(self, enabled):
        """三个写按钮解禁/置灰（「打开数据目录」是纯本地文件操作、不参与 busy 态）。"""
        for button in (self.btn_apply, self.btn_restore, self.btn_backup):
            button.setEnabled(enabled)

    def on_idle(self):
        """一轮任务结束（owner 接 `group.idle`）：解禁按钮，补刷写操作后的账本与安装态。"""
        try:
            self._set_buttons(not self._group.busy)
            if self._pending_refresh:
                self._pending_refresh = False
                self.refresh()
        except RuntimeError:                 # C++ 对象已析构
            pass
