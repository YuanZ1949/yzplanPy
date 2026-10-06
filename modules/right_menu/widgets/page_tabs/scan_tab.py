"""right_menu.widgets.page_tabs.scan_tab：四作用域右键项的扫描与隐藏/恢复。

本Tab 是 `scan.scan_scope`（纯逻辑层，只读枚举注册表）的薄壳：作用域选择 → 后台线程
扫描 → 结果表 → 行内「隐藏/恢复」。**扫描与写操作都不进 UI 线程**（前者枚举整棵
HKCR/HKLM，后者等提权子进程回读），全部走 `workers.TaskGroup` 的
`scan_scope_worker` / `apply_op_worker`。

纯逻辑（表头、格式化、`restore_marker`/`op_for` 两个写操作构造）全在同包 `scan_rows.py`
（Qt-free，可被测试直接断言），本文件只负责控件与线程接线。**恢复动作必须回读真实存在
的标记值名**：scan 行只有一个 `disabled` 布尔，写死 `name=None`（≡ `LegacyDisable`）
会删错「系统项用 `ProgrammaticAccessOnly` 隐藏」的标记。

页面是 backend 的单一来源：本Tab 一律靠 `backend=` 注入（缺省才惰性建
`Win32Backend`），测试注入 `FakeRegistry` 即可零真实注册表读写。owner（页面）负责把
`group.idle` 接到 `on_idle()`——按钮解禁与写后补刷都收在这里。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import make_button, make_combo, make_label, make_line_edit

from ... import scan, workers
from ...registry_backend import Win32Backend
from .. import confirm, make_card_block, notify
from ..tables import fill_action_cell, fill_table, make_table
from .scan_rows import COL_ACTION, COL_COMMAND, COL_STATE
from .scan_rows import EMPTY_HINT, HEADERS, HINT_IDLE, SCOPE_LABELS
from .scan_rows import action_label as _action_label
from .scan_rows import op_for, short, scope_text

# 有意 re-export：实现已下沉到 Qt-free 的 scan_rows，但 `scan_tab._restore_marker` 是
# T6-M7 契约的公共路径（测试与后续任务都从这里取，省得自己数相对层数）；本文件不引用它。
from .scan_rows import restore_marker as _restore_marker  # noqa: F401

_, QtCore, QtGui, QtWidgets = import_qt()


class ScanTab(QtWidgets.QWidget):
    """四作用域（文件/文件夹/文件夹背景/驱动器）右键项的扫描与隐藏恢复。"""

    def __init__(self, owner, group, *, parent=None, page=None, backend=None):
        super().__init__(parent)
        self._owner = owner
        self._group = group
        self._page = page
        self._backend = backend if backend is not None else Win32Backend()
        self._rows = []              # 最近一次扫描结果（过滤只作用它，不重扫）
        self._pending_refresh = False
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(sizing()["radius_xs"])
        root.addWidget(self._build_params())
        root.addWidget(self._build_results(), 1)
        self.hint = make_label(HINT_IDLE, role="caption", parent=self)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

    # ── 作用域参数区 ────────────────────────────────────────────
    def _build_params(self):
        card, lay = make_card_block("扫描参数", parent=self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        # 先建 combo（items 一次性灌入）再连 currentIndexChanged：addItems 也会发该
        # 信号，连晚了会在构造期就触发一次扫描。
        self.combo_scope = make_combo([SCOPE_LABELS[s] for s in scan.SCOPES],
                                      parent=card)
        self.combo_scope.currentIndexChanged.connect(self.refresh)
        self.edit_search = make_line_edit("搜索名称或命令…", parent=card)
        self.edit_search.textChanged.connect(self._on_search)
        row.addWidget(make_label("作用域", role="caption", parent=card))
        row.addWidget(self.combo_scope)
        row.addWidget(make_label("搜索", role="caption", parent=card))
        row.addWidget(self.edit_search, 1)
        self.btn_refresh = make_button("刷新", parent=card)
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.btn_refresh)
        lay.addLayout(row)
        return card

    def _build_results(self):
        card, lay = make_card_block(None, parent=self)
        self.title = make_label("扫描结果", role="caption", parent=card)
        lay.addWidget(self.title)
        self.table = make_table(HEADERS, parent=card)
        lay.addWidget(self.table)
        return card

    # ── 扫描 ────────────────────────────────────────────────────
    def _scope_key(self):
        """当前作用域键；下标越界（理论上不可达）时回退到第一个。"""
        index = self.combo_scope.currentIndex()
        return scan.SCOPES[index] if 0 <= index < len(scan.SCOPES) else scan.SCOPES[0]

    def refresh(self, *_args):
        """扫描当前作用域。忙时拒绝并提示（同一 TaskGroup 串行化）。"""
        if self._group.busy:
            self.hint.setText("上一项任务还在跑，请等它结束。")
            return False
        scope = self._scope_key()
        self.btn_refresh.setEnabled(False)
        ok = self._group.start(
            lambda ctx: workers.scan_scope_worker(ctx, self._backend, scope),
            on_ok=self._on_rows, on_err=self._on_failed, label=f"scan:{scope}")
        if not ok:
            self.btn_refresh.setEnabled(True)
            self.hint.setText("扫描任务未能启动。")
            return False
        self.hint.setText(f"正在扫描「{SCOPE_LABELS[scope]}」右键项…")
        return True

    def _on_rows(self, rows):
        self.btn_refresh.setEnabled(True)
        self.hint.setText(self._hint_for(len(rows or []), self._apply_rows(rows)))

    def _apply_rows(self, rows):
        """存最近结果快照 + 重填表 → 返回渲染出的行数。

        与 `_render` 分开是因为「收下这批行」和「把手上这批行画出来」是两件事：前者
        只在扫描/补刷之后发生一次，后者每改一次搜索框都要来一遍。合成一个方法就没法
        在不碰 `_rows` 的前提下直接测「一批行渲染成什么样」。
        """
        self._rows = list(rows or [])
        return self._render()

    def _on_failed(self, kind, text):
        self.btn_refresh.setEnabled(True)
        self.hint.setText(text.replace("\n", " "))
        notify(self, "扫描失败", text, error=True)

    def _on_search(self, *_args):
        """搜索框变化：只重填表，不重扫（重扫一次要几秒，逐字触发会打爆注册表读）。"""
        self._render()

    def _hint_for(self, total, shown):
        if total == 0:
            return EMPTY_HINT
        if shown < total:
            return f"共 {total} 项，匹配当前搜索 {shown} 项（搜索只过滤已扫到的结果）。"
        return f"共 {total} 项；点行尾「隐藏」把它从右键菜单里去掉（可随时恢复）。"

    def _filtered(self, rows):
        """按搜索框过滤：显示名或命令**子串**包含（casefold，不区分大小写）；空搜索原样返回。

        行字段一律 `.get()` 兜底：扫描结果来自注册表，缺 `command`（系统内建伪项）或
        `display_name` 的畸形行都不能让过滤崩在 UI 线程上。
        """
        query = (self.edit_search.text() or "").strip().casefold()
        rows = list(rows or [])
        if not query:
            return rows
        return [r for r in rows
                if query in str(r.get("display_name") or "").casefold()
                or query in str(r.get("command") or "").casefold()]

    # ── 渲染 ────────────────────────────────────────────────────
    def _render(self):
        """按当前搜索过滤后整表重填 → 返回渲染出的行数。

        操作列**不走** `fill_table` 的 `actions`：那套接口的按钮文字是每列一份的常量，
        而本表一行只放「隐藏」or「恢复」其中之一（文字随 `disabled` 变），故填完数据
        列后按行自己铺 `fill_action_cell`。铺按钮期间必须关排序：重排行会让按钮文字
        与行错位（这正是 `fill_table` 内部把按钮排在 `setSortingEnabled(True)` 之前
        的同一个理由）。
        """
        rows = self._filtered(self._rows)
        table = self.table
        fill_table(
            table, rows,
            (("display_name", None), ("scope", lambda v, _r: scope_text(v)),
             ("command", lambda v, _r: short(v)),
             ("hive", lambda v, _r: str(v or "").upper()),
             ("disabled", None), (None, None)),
            chips={COL_STATE: lambda r: ("已隐藏", "warning") if r.get("disabled")
                   else ("显示", "success")})
        table.setSortingEnabled(False)
        for index, row in enumerate(rows):
            fill_action_cell(table, index, COL_ACTION,
                             ((_action_label(row), row),), self._on_action)
        table.setSortingEnabled(True)
        self._apply_tooltips(rows)
        self.title.setText(f"扫描结果（{len(rows)} / {len(self._rows)} 项）")
        return len(rows)

    def _apply_tooltips(self, rows):
        """给命令列补全文 tooltip。

        `fill_table` 的格式化函数只能产出字符串，塞不进 ToolTipRole；此时表格仍是插入
        序（没有排序指示时 `setSortingEnabled` 不重排行），故按下标对齐，并按「截断后
        的显示文本」建索引以避开下标假设。
        """
        full = {}
        for row in rows:
            full.setdefault(short(row.get("command")), str(row.get("command") or ""))
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_COMMAND)
            if item is None:
                continue
            text = full.pop(item.text(), None)
            if text:
                item.setToolTip(text)

    # ── 行内操作 ────────────────────────────────────────────────
    def _on_action(self, row):
        """行尾按钮：一行只放「隐藏」或「恢复」其一（`_action_label` 决定文字）。"""
        action = "restore" if row.get("disabled") else "disable"
        label = _action_label(row)
        detail = ("隐藏只写一个标记值名，不删除任何内容，可随时恢复。"
                  if action == "disable" else "恢复会删掉隐藏标记，还原这个菜单项。")
        if not confirm(self, f"{label}右键项",
                       f"确认{label}这个右键项？\n\n"
                       f"· 名称：{row.get('display_name') or '(无)'}\n"
                       f"· 来源：{str(row.get('hive') or '').upper()}"
                       f" {row.get('key_path')}\n\n{detail}", ok_text=label):
            return False
        ok = self._group.start(
            lambda ctx: workers.apply_op_worker(
                ctx, self._backend, op_for(action, self._backend, row)),
            on_ok=self._on_op_result, on_err=self._on_op_failed,
            label=f"{action}:{row.get('key_path')}")
        if not ok:
            self.hint.setText("上一项任务还在跑，请等它结束再操作。")
            return False
        self.btn_refresh.setEnabled(False)
        self.hint.setText(f"正在{label}「{row.get('display_name') or row.get('key_path')}」…")
        return True

    def _on_op_result(self, result):
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        detail = (result.get("detail") or "") if isinstance(result, dict) else ""
        notify(self, "操作完成" if ok else "操作失败", detail, error=not ok)
        self.hint.setText(detail or ("操作已完成。" if ok else "操作失败。"))
        # 成功才补刷：表格此刻还停在上一次的快照。真正的刷新推迟到 idle（见 on_idle）——
        # on_ok 跑在任务 settled **之前**，此刻 group 仍 busy，立刻 refresh 会被拒。
        self._pending_refresh = ok

    def _on_op_failed(self, kind, text):
        self.hint.setText(text.replace("\n", " "))
        notify(self, "操作失败", text, error=True)

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
