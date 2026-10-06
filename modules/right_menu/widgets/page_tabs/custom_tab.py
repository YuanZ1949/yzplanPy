r"""right_menu.widgets.page_tabs.custom_tab：自定义右键菜单项的账本表 + 增删改排。

本 Tab 是 `custom`（纯逻辑层：注册表投影 + 账本 CRUD + JSON 导入导出）的薄壳：一条账本 →
一张表（顺序/标题/作用域/扩展名/命令/操作）+ 行内「编辑/删除/上移/下移」+ 顶部「新建项/导入/
导出」+ 「刷新」。表头列下标、中文标签↔DOM 枚举映射、扩展名文本互转、「本行铺哪些按钮」与
三类结果文案全在同包 `custom_rows.py`（Qt-free，测试可直接断言）；本文件只管控件与线程接线。
页面是 backend 的单一来源：一律靠 `backend=` 注入（缺省才惰性建 `Win32Backend`），测试注入
`FakeRegistry` 即可零真实注册表读写。

**读同步、写异步**：账本是本地 JSON（`store.get_custom_items` 毫秒级），为它起 QThread 只会
多一层悬挂线程风险——与 `classic_tab` 同步读 HKCU 同一判断，故 `refresh()` 直接读，且**构造尾
就调一次**。保存/删除/导入则一律经 `workers.TaskGroup`：它们要落注册表（HKCU 直写也要逐条回读）、
要落盘，导入还要整批 `sync_all`；**导出是例外**（纯本地文件写）。**唯一同步写账本的是 `move`，
故它必须自己判 busy**——`start` 的串行化只挡新任务。

**上下移只改账本顺序，不碰注册表**（`move` 的硬约定）：注册表里那些 shell 键之间**没有顺序
语义**（菜单顺序由 `Position` 值与注册表枚举顺序决定），为「换个顺序」去重写一遍投影既慢又平
白多一次 UAC 风险。故 `move` 同步改 `set_custom_items` 后立刻重绘，不起线程、不调 `sync_all`。

**两个可测性缝**：`confirm_fn` 注入参数绕开删除确认的模态框；**模块一律调用时取属性**
（`custom.save_item(...)` / `rm_store.get_custom_items()` 而非 `from ...custom import save_item`），
否则 monkeypatch 拦不到——`store.STATE_PATH` 正是在调用时读的（测试指到 `tmp_path`），
`custom.elevate.run_job` 同理。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_label

from ... import custom, store as rm_store, workers
from ...registry_backend import Win32Backend
from .. import confirm, editor_dialog, make_card_block, notify
from ..tables import fill_action_cell, fill_table, make_table
from . import custom_rows as rows

_, QtCore, QtGui, QtWidgets = import_qt()


class CustomTab(QtWidgets.QWidget):
    """自定义右键菜单项：账本表 + 新建/编辑/删除/排序 + 导入导出。"""

    def __init__(self, owner, group, *, parent=None, page=None, backend=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._page = page
        self._backend = backend if backend is not None else Win32Backend()
        self._rows = []              # 最近一次渲染用的显示行快照（custom_rows.display_rows）
        self._pending_refresh = False
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_params())
        root.addWidget(self._build_results(), 1)
        self.hint = make_label(rows.HINT_IDLE, role="caption", parent=self)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.refresh()               # 构造尾同步渲染：账本是本地 JSON，不起线程（见 docstring）

    # ── 参数区 / 结果区 ──────────────────────────────────────────
    def _build_params(self):
        card, lay = make_card_block("自定义项", parent=self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        self.btn_refresh = make_button("刷新", parent=card)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_add = make_button("新建项", kind="primary", parent=card)
        self.btn_add.clicked.connect(self.add_item)
        self.btn_import = make_button("导入", parent=card)
        self.btn_import.clicked.connect(self.import_items)
        self.btn_export = make_button("导出", parent=card)
        self.btn_export.clicked.connect(self.export_items)
        for button in (self.btn_refresh, self.btn_add, self.btn_import, self.btn_export):
            row.addWidget(button)
        row.addStretch(1)
        lay.addLayout(row)
        return card

    def _build_results(self):
        card, lay = make_card_block(None, parent=self)
        self.title = make_label("自定义菜单项", role="caption", parent=card)
        lay.addWidget(self.title)
        self.table = make_table(rows.HEADERS, parent=card)
        lay.addWidget(self.table)
        return card

    # ── 账本读 + 渲染 ────────────────────────────────────────────
    def refresh(self, *_args):
        """同步重读账本并重绘表 → 返回渲染出的行数（本地 JSON，不起线程）。"""
        return self._apply_rows(rm_store.get_custom_items())

    def _apply_rows(self, items):
        """收下这批账本条目 + 重绘 + 更新提示 → 返回行数（与 `_render` 分开同 scan/shellnew）。"""
        self._rows = rows.display_rows(items)
        count = self._render()
        self.hint.setText(rows.hint_for(count))
        return count

    def _render(self):
        """整表重填（文本列走 `fill_table`，操作列按行铺；列规格在 `custom_rows`）→ 返回行数。

        标题/命令列不手工截断，QTableWidget 的 delegate 自己 elide 成省略号。"""
        table = self.table
        fill_table(table, self._rows, rows.COLUMNS, numeric=rows.NUMERIC_COLS)
        table.setSortingEnabled(False)
        for index, row in enumerate(self._rows):
            fill_action_cell(table, index, rows.COL_ACTION, rows.actions_for(row),
                             self._on_action)
        table.setSortingEnabled(True)
        self.title.setText(f"自定义菜单项（{len(self._rows)} 项）")
        return len(self._rows)

    # ── 行内动作分派 ────────────────────────────────────────────
    def _on_action(self, arg):
        """行尾按钮分派：`arg = (动作, id)`。删除走确认框，其余各自的方法。上移/下移合成一个
        分支：动作名 `move_up`/`move_down` 与 delta 同向（−1/+1），比再加一个分支更不容易写反。"""
        action, ident = arg
        if action == "edit":
            return self.edit_item(ident)
        if action == "delete":
            return self.delete_item(ident)
        return self.move(ident, -1 if action == "move_up" else 1)

    def move(self, item_id, delta):
        """账本内上移/下移一条（`delta` = -1 上移 / +1 下移）→ 成功 True。

        **只改账本顺序**（理由见模块 docstring）；找不到该 id 或已到边界都返回 False。

        **必须自己判 busy（lost update 防线）**：保存/导入 worker 正带着它自己读到的账本快照在跑，
        此刻点「上移」会用旧快照写回整个账本、worker 随后把它那份覆盖回去——排序静默丢失。
        `move` 不起线程，绕过了 `TaskGroup` 的串行化。"""
        if self._group.busy:
            self.hint.setText(rows.HINT_BUSY)
            return False
        items = rm_store.get_custom_items()
        index = rows.find_index(items, item_id)
        target = index + (1 if delta > 0 else -1)
        if index < 0 or not 0 <= target < len(items):
            return False
        items.insert(target, items.pop(index))
        if not rm_store.set_custom_items(items):
            return False
        self._apply_rows(items)
        return True

    # ── 新建 / 编辑 / 删除 ──────────────────────────────────────
    def add_item(self):
        """新建项：弹编辑器（`item=None` → 对话框层生成新 id）→ 保存进线程。"""
        return self._save_dialog(None, "custom:save", rows.working_hint("save"))

    def edit_item(self, item_id):
        """编辑：按 id 现读账本取原条目 → 弹编辑器（**保留原 id**，否则等于新建一条）。"""
        item = rows.find_item(rm_store.get_custom_items(), item_id)
        if item is None:
            ident = rows.text(item_id)
            notify(self, "找不到该项", f"账本里没有 id 为 {ident} 的自定义项。", error=True)
            return False
        ident = rows.item_id(item)
        title = rows.text(item.get("title")) or ident
        return self._save_dialog(item, f"custom:save:{ident}",
                                 rows.working_hint("save", title))

    def _save_dialog(self, item, label, hint_text):
        """新建/编辑共用收尾：弹对话框 → 确定后 `save_item_worker` 进线程。"""
        dlg = editor_dialog.CustomItemDialog(self, item=item)
        try:
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return False
            dom = dlg.value()
        finally:
            dlg.deleteLater()        # 反复开关对话框不能靠 parent 兜底释放
        return self._start_write(label, lambda ctx: workers.save_item_worker(
            ctx, self._backend, dom), hint_text)

    def delete_item(self, item_id, *, confirm_fn=None):
        """删一条自定义项（含它全部子菜单的注册表投影）——**唯一不可逆的动作**，先确认。

        `confirm_fn` 是可测性缝（缺省走模态 `confirm`；`parent=None` 时它一律返回 False）。"""
        ident = rows.text(item_id)
        if not (confirm_fn or confirm)(self, "删除自定义项",
                                       rows.delete_confirm_text(ident), ok_text="删除"):
            return False
        return self._start_write(
            f"custom:delete:{ident}",
            lambda ctx: workers.delete_item_worker(ctx, self._backend, ident),
            rows.working_hint("delete", ident))

    # ── 导入 / 导出 ─────────────────────────────────────────────
    def _pick_path(self, save, title):
        """统一的文件选择（`save=True` 走保存框）；返回空串 = 用户取消。"""
        getter = (QtWidgets.QFileDialog.getSaveFileName if save
                  else QtWidgets.QFileDialog.getOpenFileName)
        return getter(self, title, rows.EXPORT_NAME if save else "", rows.FILE_FILTER)[0]

    def export_items(self, *, path=None):
        """导出账本为 JSON → 成功 True。`path` 缺省弹保存框，取消（空串）返回 False。"""
        target = path or self._pick_path(True, "导出自定义项")
        if not target:
            return False
        ok, title, body, hint = rows.result_view(custom.export_items(target))
        notify(self, title, body, error=not ok)
        self.hint.setText(hint)
        return ok

    def import_items(self, *, path=None):
        """导入 JSON → 起线程（导入会整批 `sync_all`，含注册表写）→ 成功后补刷表。"""
        target = path or self._pick_path(False, "导入自定义项")
        if not target:
            return False
        return self._start_write("custom:import", lambda ctx: custom.import_items(
            self._backend, target), rows.working_hint("import"))

    # ── 线程接线 ────────────────────────────────────────────────
    def _start_write(self, label, worker, hint_text):
        """所有写动作的统一入口：起线程；按钮解禁交给 `on_idle`（忙则拒绝并提示）。"""
        started = self._group.start(worker, on_ok=self._on_op_result,
                                    on_err=self._on_failed, label=label)
        if not started:
            self.hint.setText(rows.HINT_BUSY)
            return False
        self._set_buttons(False)
        self.hint.setText(hint_text)
        return True

    def _on_op_result(self, result):
        ok, title, body, hint = rows.result_view(result)
        notify(self, title, body, error=not ok)
        self.hint.setText(hint)
        self._pending_refresh = ok  # 成功才补刷，且推迟到 idle（on_ok 跑在 settled 之前）

    def _on_failed(self, kind, text):
        self._set_buttons(True)
        self.hint.setText(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

    # ── 状态与清理 ──────────────────────────────────────────────
    def _set_buttons(self, enabled):
        """三个写按钮解禁/置灰（导出是同步文件写、不参与 busy 态，故不含它）。"""
        for button in (self.btn_refresh, self.btn_add, self.btn_import):
            button.setEnabled(enabled)

    def on_idle(self):
        """一轮任务结束（owner 接 `group.idle`）：解禁按钮，补刷写操作后的账本快照。"""
        try:
            self._set_buttons(not self._group.busy)
            if self._pending_refresh:
                self._pending_refresh = False
                self.refresh()
        except RuntimeError:                 # C++ 对象已析构
            pass
