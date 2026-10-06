"""right_menu.widgets.page_tabs.shellnew_tab：Explorer「新建」菜单项的隐藏/恢复/删除/新增。

本 Tab 是 `shellnew`（纯逻辑层：枚举两个 hive 下带 `ShellNew` 子键的扩展名 + 四个写动作）
的薄壳：刷新 → `scan_shellnew_worker` 后台线程 → 结果表 → 行内「隐藏/恢复/删除」+ 顶部
「新增模板」。

**四个写动作一律进线程**：HKCU 直写虽是毫秒级，但 HKLM 项在 `shellnew._write_rename`
内部要走 UAC 提权子进程并等它回读（阻塞数秒），统一用 `group.start` 包一层，UI 永不冻结。

**操作列不走 `fill_table` 的 `actions`**：那个接口的按钮文字是每列一份的常量，而本表每行
按钮组不同（已隐藏 → 只给「恢复」；未隐藏 → 「隐藏」，HKCU 项再加「删除」）。故填完文本/
胶囊列后按行自己铺 `fill_action_cell`（铺按钮期间关排序，重排行会让按钮与行错位——与
`scan_tab._render` 同一个理由）。

**删除是唯一不可逆的动作**（整棵移除 `ShellNew` 子键），故先 `confirm`（确认框经
`confirm_fn` 缝注入，测试可绕开模态）；其余动作幂等且可逆（隐藏只是给值名加后缀），不打断
用户。新增只写 HKCU（`create_shellnew` 的硬约束），故对话框不提供 hive 选择。表头 /
kind→胶囊映射 / 「本行该铺哪些按钮」等纯决策全在同包 `shellnew_rows.py`（Qt-free，测试
可直接断言），本文件只负责控件与线程接线。

页面是 backend 的单一来源：本 Tab 一律靠 `backend=` 注入（缺省才惰性建 `Win32Backend`），
测试注入 `FakeRegistry` 即可零真实注册表读写。owner（页面）把 `group.idle` 接到
`on_idle()`——按钮解禁与写后补刷都收在这里。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_combo, make_label, make_line_edit

from ... import shellnew, workers
from ...registry_backend import Win32Backend
from .. import confirm, make_card_block, notify
from ..tables import fill_action_cell, fill_table, make_table
from .shellnew_rows import ADD_KINDS, COL_ACTION, COL_KIND, COL_STATE, HINT_IDLE, HEADERS
from .shellnew_rows import actions_for, add_kind, hint_for, kind_chip, state_chip, write

_, QtCore, QtGui, QtWidgets = import_qt()


class ShellNewTab(QtWidgets.QWidget):
    """Explorer「新建」菜单项的扫描、隐藏/恢复/删除与新增模板。"""

    def __init__(self, owner, group, *, parent=None, page=None, backend=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._page = page
        self._backend = backend if backend is not None else Win32Backend()
        self._rows = []              # 最近一次扫描结果快照
        self._pending_refresh = False
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_params())
        root.addWidget(self._build_results(), 1)
        self.hint = make_label(HINT_IDLE, role="caption", parent=self)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

    # ── 参数区 / 结果区 ──────────────────────────────────────────
    def _build_params(self):
        card, lay = make_card_block("新建菜单", parent=self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        self.btn_refresh = make_button("刷新", parent=card)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_add = make_button("新增模板", kind="primary", parent=card)
        self.btn_add.clicked.connect(self._add_dialog)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_add)
        row.addStretch(1)
        lay.addLayout(row)
        return card

    def _build_results(self):
        card, lay = make_card_block(None, parent=self)
        self.title = make_label("新建菜单项", role="caption", parent=card)
        lay.addWidget(self.title)
        self.table = make_table(HEADERS, parent=card)
        lay.addWidget(self.table)
        return card

    # ── 扫描 ────────────────────────────────────────────────────
    def refresh(self, *_args):
        """扫描两个 hive 的 ShellNew 项。忙时拒绝并提示（同一 TaskGroup 串行化）。"""
        started = self._group.start(
            lambda ctx: workers.scan_shellnew_worker(ctx, self._backend),
            on_ok=self._on_rows, on_err=self._on_failed, label="shellnew:scan")
        if not started:
            self.hint.setText("上一项任务还在跑，请等它结束。")
            return False
        self.btn_refresh.setEnabled(False)
        self.hint.setText("正在扫描「新建」菜单项…")
        return True

    def _on_rows(self, rows):
        self.btn_refresh.setEnabled(True)
        self.hint.setText(hint_for(self._apply_rows(rows)))

    def _apply_rows(self, rows):
        """存最近结果快照 + 重填表 → 返回渲染出的行数。

        与 `_render` 分开同 scan_tab：「收下这批行」与「把手上这批行画出来」是两件事，
        分开后测试才能在不触发扫描线程的前提下直接断言一批行渲染成什么样。"""
        self._rows = list(rows or [])
        return self._render()

    def _on_failed(self, kind, text):
        self.btn_refresh.setEnabled(True)
        self.hint.setText(text.replace("\n", " "))
        notify(self, "扫描失败", text, error=True)

    # ── 渲染 ────────────────────────────────────────────────────
    def _render(self):
        """整表重填（文本/胶囊列走 `fill_table`，操作列按行铺）→ 返回渲染出的行数。

        模板列不手工截断：QTableWidget 默认 delegate 会自行 elide 成省略号。"""
        rows, table = self._rows, self.table
        fill_table(
            table, rows,
            (("ext", None), ("kind", None), ("template", None), ("hidden", None),
             (None, None)),
            chips={COL_KIND: kind_chip, COL_STATE: state_chip})
        table.setSortingEnabled(False)
        for index, row in enumerate(rows):
            fill_action_cell(table, index, COL_ACTION, actions_for(row), self._on_action)
        table.setSortingEnabled(True)
        self.title.setText(f"新建菜单项（{len(rows)} 项）")
        return len(rows)

    # ── 行内写操作 ──────────────────────────────────────────────
    def _on_action(self, arg):
        """行尾按钮分派：`arg = (动作, 行)`。删除走确认框，其余直接进线程。"""
        action, row = arg
        if action == "delete":
            return self.delete_item(row)
        label = "恢复" if action == "restore" else "隐藏"
        return self._start_write(
            f"shellnew:{action}:{row.get('key_path')}",
            lambda ctx: write(action, self._backend, row),
            f"正在{label}「{row.get('ext') or row.get('key_path')}」…")

    def delete_item(self, row, *, confirm_fn=None):
        """删掉一个 ShellNew 子键——**唯一不可逆的动作**，先确认再起线程。

        `confirm_fn` 是可测性缝：缺省走 `confirm`（模态框），测试注入恒真/恒假函数即可把
        「点了删除」与「点了取消」两条路径都钉住。HKLM 项不给按钮（`actions_for` 过滤），
        故不再重复判断 hive——真收到 hklm 也由 `delete_shellnew` 自己拒绝。
        """
        if not (confirm_fn or confirm)(
                self, "删除新建菜单项",
                f"确认删除「{row.get('ext') or ''}」的新建菜单项？\n\n"
                f"· 来源：{str(row.get('hive') or '').upper()} {row.get('key_path')}\n\n"
                "删除会整棵移除该 ShellNew 键，本模块无法一键还原。", ok_text="删除"):
            return False
        return self._start_write(
            f"shellnew:delete:{row.get('key_path')}",
            lambda ctx: write("delete", self._backend, row),
            f"正在删除「{row.get('ext') or row.get('key_path')}」的新建项…")

    def create_item(self, ext, kind, *, template_path=None):
        """新增一个 ShellNew 项（只写 HKCU）→ 起线程 + notify。失败文案由操作层给出。"""
        return self._start_write(
            f"shellnew:create:{ext}",
            lambda ctx: shellnew.create_shellnew(
                self._backend, str(ext or "").strip(), name=None, kind=kind,
                template_path=template_path or None),
            f"正在新增「{str(ext or '').strip()}」的新建项…")

    def _start_write(self, label, worker, hint_text):
        """四个写动作的统一入口：起线程；按钮解禁交给 `on_idle`。"""
        started = self._group.start(worker, on_ok=self._on_op_result,
                                    on_err=self._on_failed, label=label)
        if not started:
            self.hint.setText("上一项任务还在跑，请等它结束再操作。")
            return False
        self.btn_refresh.setEnabled(False)
        self.hint.setText(hint_text)
        return True

    def _on_op_result(self, result):
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        detail = (result.get("detail") or "") if isinstance(result, dict) else ""
        notify(self, "操作完成" if ok else "操作失败", detail, error=not ok)
        self.hint.setText(detail or ("操作已完成。" if ok else "操作失败。"))
        # 成功才补刷：表格此刻还停在上一次的快照。真正的刷新推迟到 idle（见 on_idle）——
        # on_ok 跑在任务 settled **之前**，此刻 group 仍 busy，立刻 refresh 会被拒。
        self._pending_refresh = ok

    # ── 新增对话框 ──────────────────────────────────────────────
    def _add_dialog(self):
        """「新增模板」对话框：扩展名 + 类型（+ 模板路径）→ `create_item` 走线程。"""
        box = QtWidgets.QDialog(self)
        box.setWindowTitle("新增新建菜单项")
        lay = QtWidgets.QVBoxLayout(box)
        margin = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.setSpacing(sizing()["dialog_spacing"])
        ext_row = QtWidgets.QHBoxLayout()
        ext_row.addWidget(make_label("扩展名", role="caption", parent=box))
        edit_ext = make_line_edit("扩展名，如 .md", parent=box)
        ext_row.addWidget(edit_ext, 1)
        lay.addLayout(ext_row)
        kind_row = QtWidgets.QHBoxLayout()
        kind_row.addWidget(make_label("类型", role="caption", parent=box))
        combo_kind = make_combo([text for text, _ in ADD_KINDS], parent=box)
        kind_row.addWidget(combo_kind, 1)
        lay.addLayout(kind_row)
        tpl_row = QtWidgets.QHBoxLayout()
        tpl_row.addWidget(make_label("模板文件", role="caption", parent=box))
        edit_tpl = make_line_edit("仅「模板文件」需要", parent=box)
        btn_pick = make_button("选择…", parent=box)
        btn_pick.clicked.connect(lambda: self._pick_template(edit_tpl))
        tpl_row.addWidget(edit_tpl, 1)
        tpl_row.addWidget(btn_pick)
        lay.addLayout(tpl_row)
        lay.addWidget(make_label(
            "只写入当前用户（HKCU）。同一扩展名已有新建项时会拒绝，不会叠加第二个。",
            role="caption", parent=box))
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = make_button("取消", parent=box)
        btn_cancel.clicked.connect(box.reject)
        btn_ok = make_button("新增", kind="primary", parent=box)
        btn_ok.clicked.connect(box.accept)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_ok)
        lay.addLayout(buttons)
        if box.exec() != QtWidgets.QDialog.Accepted:
            return False
        return self.create_item(edit_ext.text(), add_kind(combo_kind.currentIndex()),
                                template_path=edit_tpl.text().strip())

    def _pick_template(self, edit):
        """文件选择框填进模板路径输入框；用户取消（空串）就什么都不改。"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择模板文件")
        if path:
            edit.setText(path)
        return path

    # ── 状态与清理 ──────────────────────────────────────────────
    def on_idle(self):
        """一轮任务结束（owner 接 `group.idle`）：解禁按钮，补刷写操作后的快照。"""
        try:
            self.btn_refresh.setEnabled(not self._group.busy)
            if self._pending_refresh:
                self._pending_refresh = False
                self.refresh()
        except RuntimeError:                 # C++ 对象已析构
            pass
