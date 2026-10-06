r"""right_menu.widgets.editor_dialog：自定义项的表单编辑器（一个 DOM ↔ 一屏控件）。

**不用 QMessageBox 系**：`MessageBox` 只能放纯文本，做不了「标题/目标/参数 + 子菜单树」这种
多控件表单，故这里自建 `QDialog` 子类；控件全部来自 `ui/widgets.py` 的令牌化工厂（本文件不写
任何 QSS、不定义调色板、不写像素字面量 —— AGENTS.md 规则 1~5）。

**`value()` 返回完整 DOM 而非「表单片段」**：`custom_dom.validate_item` 会对 children 递归
取键、`custom.save_item` 靠 `id` 做 upsert、`custom._tree` 靠 `scope`/`ext_filter` 算投影根，
半截 dict 会静默丢字段。故缺的那几键在 `value()` 里显式补默认值（`hive="hkcu"`、
`position="default"`、`icon=""`、`extended=False`、`children=[]`）。

**id 的决定权在本层**（`custom.py` 只按 id upsert、从不生成）：新建 → `custom_rows.new_id()`
（`uuid4().hex[:8]`）；编辑 → **保留传入 item 的原 id**。换 id 就等于新建一条并让旧条目的
注册表投影变成再也点不到的孤儿项，故编辑路径必须把原 id 原样带回去。

**校验拦在 `accept()` 里**：errors 非空 → `notify(error=True)` 且**不放行**（对话框留在原地，
用户改完再点确定）；warnings 非空 → 照常提示但**放行**（占位符没加引号这类风险该由用户判断，
替他拒绝只会让人以为功能坏了）。

**子菜单只做一层**：`validate_item` 允许 children 任意深度（更深的结构由文件导入支持），但
无限嵌套的 UI 没有价值——子项与父项共用同一套「标题/目标/参数」，再套一层要多一套控件与一套
校验反馈。故树固定两层（顶层子项 + 表内两列单元格），子项的 `scope`/`ext_filter` **继承父表
单当前值**、参数继承父参数，纯粹是为了让递归校验有合法值可查：投影时子项只挂在父自己的
`shell` 键下（`custom._tree` 的 parent 分支根本不看这几个字段）。

**`custom_rows` 的 import 放在 `__init__` 体内**：`page_tabs` 包会 import 本模块（custom_tab
要弹它），顶层反向 import 即成环（`widgets.page_tabs` → `widgets.editor_dialog` →
`widgets.page_tabs`）。同 `page.py` 惰性建 backend 的同一手法：只在真正构造对话框时才付这个
代价，且此刻 `page_tabs` 包必然已加载完毕。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import (make_button, make_checkbox, make_combo, make_label,
                        make_line_edit)

from .. import custom
from . import notify

_, QtCore, QtGui, QtWidgets = import_qt()

#: 子菜单树两列的表头（只有标题与目标可编辑；参数继承父项）
CHILD_HEADERS = ("标题", "目标")
#: 卡尾固定说明：把「命令模板不展开」「只写 HKCU」两条硬约定写在眼前
_NOTE = ("命令模板 %1（首个选中项）/%*（全部）/%V（当前目录）会原样写进注册表，由资源管理器"
         "展开；只写入当前用户（HKCU），不会触碰 HKLM。")


class CustomItemDialog(QtWidgets.QDialog):
    """自定义项的表单编辑器：新建（`item=None`）与编辑（传入原 item）共用同一个类。"""

    def __init__(self, parent=None, *, item=None):
        super().__init__(parent)
        from .page_tabs import custom_rows as rows      # 见模块 docstring：防 import 环
        self._rows = rows
        self._item = item if isinstance(item, dict) else {}
        # 编辑必须保留原 id；历史条目缺 id（半截导入）时才补一个新身份
        self._id = rows.item_id(self._item) or rows.new_id()
        self.setWindowTitle("编辑自定义项" if self._item else "新建自定义项")
        lay = QtWidgets.QVBoxLayout(self)
        margin = sizing()["dialog_margin"] // 2
        lay.setContentsMargins(margin, margin, margin, margin)
        lay.setSpacing(sizing()["dialog_spacing"])
        self._build_fields(lay)
        self._build_children(lay)
        note = make_label(_NOTE, role="caption", parent=self)
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(self._build_buttons())
        self._load()

    # ── 组装 ────────────────────────────────────────────────────
    def _field(self, lay, caption, widget):
        """一行「标题 + 控件」：控件吃掉整行余量，标题按内容定宽。"""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        row.addWidget(make_label(caption, role="caption", parent=self))
        row.addWidget(widget, 1)
        lay.addLayout(row)
        return widget

    def _build_fields(self, lay):
        """九个表单项（顺序即视觉顺序，与模块 docstring 里列的字段一一对应）。"""
        labels = ([text for text, _ in self._rows.SCOPES],
                  [text for text, _ in self._rows.KINDS],
                  [text for text, _ in self._rows.POSITIONS])
        self.title_edit = self._field(lay, "标题", make_line_edit(
            "显示在右键菜单里的文字", parent=self))
        self.icon_edit = self._field(lay, "图标", make_line_edit(
            "图标路径（可选）", parent=self))
        self.scope_combo = self._field(lay, "作用域", make_combo(labels[0], parent=self))
        self.ext_edit = self._field(lay, "扩展名过滤", make_line_edit(
            "如 py,md，留空=全部", parent=self))
        self.kind_combo = self._field(lay, "命令类型", make_combo(labels[1], parent=self))
        self.target_edit = self._field(lay, "目标", make_line_edit(
            "程序/命令/URL", parent=self))
        self.args_edit = self._field(lay, "参数", make_line_edit(
            '如 "%1"，支持 %1/%*/%V', parent=self))
        self.workdir_edit = self._field(lay, "工作目录", make_line_edit(
            "可留空", parent=self))
        self.extended_box = self._field(lay, "Shift 限定", make_checkbox(
            "仅按住 Shift 时显示", parent=self))
        self.position_combo = self._field(lay, "位置", make_combo(labels[2], parent=self))

    def _build_children(self, lay):
        """子菜单编辑区：两列 QTreeWidget + 「加子项」「删子项」（树本身即唯一一层）。"""
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(len(CHILD_HEADERS))
        self.tree.setHeaderLabels(list(CHILD_HEADERS))
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(sizing()["radius_sm"])
        btn_add = make_button("加子项", parent=self)
        btn_add.clicked.connect(self.add_child)
        btn_del = make_button("删子项", parent=self)
        btn_del.clicked.connect(self.remove_child)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay.addLayout(row)
        return self.tree

    def _build_buttons(self):
        """底部按钮行：取消 reject、确定 accept（accept 里才有校验，见 `accept`）。"""
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        btn_cancel = make_button("取消", parent=self)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = make_button("确定", kind="primary", parent=self)
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        return row

    # ── 预填 ────────────────────────────────────────────────────
    def _load(self):
        """把传入 item 铺进控件（缺字段 / 畸形条目一律走空值，绝不抛）。"""
        rows = self._rows
        action = self._item.get("action")
        action = action if isinstance(action, dict) else {}
        self.title_edit.setText(rows.text(self._item.get("title")))
        self.icon_edit.setText(rows.text(self._item.get("icon")))
        self.scope_combo.setCurrentIndex(rows.scope_index(self._item.get("scope")))
        self.ext_edit.setText(rows.format_ext_filter(self._item.get("ext_filter")))
        self.kind_combo.setCurrentIndex(rows.kind_index(action.get("kind")))
        self.target_edit.setText(rows.text(action.get("target")))
        self.args_edit.setText(rows.text(action.get("args")))
        self.workdir_edit.setText(rows.text(action.get("workdir")))
        self.extended_box.setChecked(bool(self._item.get("extended")))
        self.position_combo.setCurrentIndex(
            rows.position_index(self._item.get("position")))
        for child in (self._item.get("children") or []):
            if isinstance(child, dict):
                self._load_child(child)

    def _load_child(self, child):
        """预填一个子项：只还原标题与目标，参数等其余字段在 `value()` 里继承父表单。"""
        action = child.get("action")
        node = self.add_child()
        node.setText(0, self._rows.text(child.get("title")))
        node.setText(1, self._rows.text(action.get("target"))
                     if isinstance(action, dict) else "")
        return node

    # ── 子菜单 ──────────────────────────────────────────────────
    def add_child(self):
        """加一个空子项并选中它（新行没有标题/目标，点确定时会被校验拦下）。"""
        node = QtWidgets.QTreeWidgetItem(self.tree, ["", ""])
        self.tree.setCurrentItem(node)
        return node

    def remove_child(self):
        """删掉当前选中的子项；没选中就什么都不做（返回 False，不弹框）。"""
        node = self.tree.currentItem()
        if node is None:
            return False
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(node))
        return True

    def _child_dom(self, node, parent):
        """树上一行 → **完整**子项 DOM（`validate_item` 递归检查，键必须给全）。"""
        return {"id": self._rows.new_id(), "title": node.text(0).strip(),
                "icon": "", "scope": parent["scope"],
                "ext_filter": list(parent["ext_filter"]), "hive": "hkcu",
                "extended": False, "position": "default",
                "action": {"kind": parent["action"]["kind"],
                           "target": node.text(1).strip(),
                           "args": parent["action"]["args"], "workdir": ""},
                "children": []}

    # ── 取值 / 校验 ─────────────────────────────────────────────
    def value(self):
        """当前控件 → 完整 DOM dict（可直接喂 `validate_item` / `save_item`）。"""
        rows = self._rows
        dom = {"id": self._id, "title": self.title_edit.text().strip(),
               "icon": self.icon_edit.text().strip(),
               "scope": rows.scope_value(self.scope_combo.currentIndex()),
               "ext_filter": rows.parse_ext_filter(self.ext_edit.text()),
               "hive": "hkcu", "extended": bool(self.extended_box.isChecked()),
               "position": rows.position_value(self.position_combo.currentIndex()),
               "action": {"kind": rows.kind_value(self.kind_combo.currentIndex()),
                          "target": self.target_edit.text().strip(),
                          "args": self.args_edit.text().strip(),
                          "workdir": self.workdir_edit.text().strip()},
               "children": []}
        for index in range(self.tree.topLevelItemCount()):
            dom["children"].append(
                self._child_dom(self.tree.topLevelItem(index), dom))
        return dom

    def accept(self):
        """确定：先校验。**errors 阻断**（留在原地让用户改），warnings 只提示不拦。"""
        report = custom.validate_item(self.value())
        errors = report.get("errors") or []
        warnings = report.get("warnings") or []
        if errors:
            notify(self, "还不能保存", "；".join(errors), error=True)
            return
        if warnings:
            notify(self, "请确认", "；".join(warnings))
        super().accept()
