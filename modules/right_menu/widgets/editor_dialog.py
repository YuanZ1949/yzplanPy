r"""right_menu.widgets.editor_dialog：自定义项的表单编辑器（一个 DOM ↔ 一屏控件）。

**不用 QMessageBox 系**：`MessageBox` 只能放纯文本，做不了「标题/目标/参数 + 子菜单树」这种
多控件表单，故这里自建 `QDialog` 子类；控件全部来自 `ui/widgets.py` 的令牌化工厂（本文件不写
任何 QSS、不定义调色板、不写像素字面量 —— AGENTS.md 规则 1~5）。

**`value()` 返回完整 DOM 而非「表单片段」**：`custom_dom.validate_item` 会对 children 递归
取键、`custom.save_item` 靠 `id` 做 upsert、`custom._tree` 靠 `scope`/`ext_filter` 算投影根，
半截 dict 会静默丢字段。故缺的那几键在 `value()` 里显式补默认值。

**两条「UI 上没有控件、但保存必须原样带回」的字段**（写死默认值就是静默数据丢失，理由见
`value` / `_child_dom` 的 docstring）：`id` 与 `hive`。id 换掉等于新建一条并让旧投影变成孤儿；
hive 写死 hkcu 等于把导入来的全局菜单搬到当前用户（旧投影还要先弹一次 UAC）。
**校验拦在 `accept()` 里**：errors 非空 → `notify(error=True)` 且**不放行**（对话框留在原地）；
warnings 非空 → 照常提示但**放行**（占位符没加引号这类风险该由用户判断，替他拒绝只会让人以为
功能坏了）。**子菜单只做一层**：树固定两层，更深的结构由文件导入支持。

**`custom_rows` 的 import 放在 `__init__` 体内**：`page_tabs` 包会 import 本模块（custom_tab
要弹它），顶层反向 import 即成环。同 `page.py` 惰性建 backend 的同一手法。
"""
from copy import deepcopy

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

from ui.widgets import (make_button, make_checkbox, make_combo, make_label,
                        make_line_edit)

from .. import custom
from . import notify

_, QtCore, QtGui, QtWidgets = import_qt()

#: 子菜单树两列的表头（只有标题与目标可编辑；参数继承父项）
CHILD_HEADERS = ("标题", "目标")
#: 卡尾固定说明：把「命令模板不展开」「写入哪个 hive」两条硬约定写在眼前。hive 那句必须准确——
#: 导入的全局条目会原样留在全局，保存时旧投影按 hklm 分组走提权通道（弹 UAC 等回读）。
_NOTE = ("命令模板 %1（首个选中项）/%*（全部）/%V（当前目录）会原样写进注册表，由资源管理器"
         "展开；新建项写入当前用户（HKCU），从文件导入的条目保留它原有的 hive 范围。")


class CustomItemDialog(QtWidgets.QDialog):
    """自定义项的表单编辑器：新建（`item=None`）与编辑（传入原 item）共用同一个类。"""

    def __init__(self, parent=None, *, item=None):
        super().__init__(parent)
        from .page_tabs import custom_rows as rows      # 见模块 docstring：防 import 环
        self._rows = rows
        self._item = item if isinstance(item, dict) else {}
        # 编辑必须保留原 id；历史条目缺 id（半截导入）时才补一个新身份
        self._id = rows.item_id(self._item) or rows.new_id()
        # hive 与子项原条目都是「UI 上没有控件、但保存必须原样带回」的字段（见 _child_dom）
        self._hive = rows.hive_of(self._item)
        self._origins = {}          # 子项 id → 原始条目深拷贝
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
        """预填一个子项：标题/目标进树；**原始条目深拷贝存进 `_origins`**（copy-through 底本）。

        行的 id 挂在树项的 UserRole 上——它是对回原条目的唯一钥匙（树项可被用户重排，按下标对齐
        的映射表一重排就张冠李戴）。缺 id 的半截导入条目在此补身份，否则 `save_item._split`
        会把所有无 id 条目当成同一条。"""
        rows = self._rows
        ident = rows.item_id(child) or rows.new_id()
        action = child.get("action")
        node = self.add_child()
        node.setText(0, rows.text(child.get("title")))
        node.setText(1, rows.text(action.get("target"))
                     if isinstance(action, dict) else "")
        node.setData(0, QtCore.Qt.ItemDataRole.UserRole, ident)
        self._origins[ident] = deepcopy(dict(child, id=ident))
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
        """树上一行 → **完整**子项 DOM（`validate_item` 递归检查，键必须给全）。

        **copy-through 是本方法存在的理由（静默数据丢失的防线）**：这个对话框只为子项暴露了标题
        与目标两列，其余字段——`kind`/`position`/`icon`/`extended`/`args`/`workdir`/`ext_filter`/
        `scope`/`hive`，以及 `children` 里的**孙节点**——在 UI 上没有控件。从零重建等于「用默认
        值 + 父表单的值」把用户原样覆写掉，孙节点更是直接消失：保存时 `custom._sync_item` 的
        stale delete_tree 会先删掉它们的注册表投影、再把拍平的子树写回账本。故对得上原 id 的行
        **深拷贝原条目后只覆盖 title 与 target**（深拷贝是必须的：`value()` 会被反复调用）。
        """
        ident = node.data(0, QtCore.Qt.ItemDataRole.UserRole)
        title, target = node.text(0).strip(), node.text(1).strip()
        original = self._origins.get(ident) if isinstance(ident, str) else None
        if original is None:                     # 新加的行：继承父表单（只为过递归校验）
            return {"id": self._rows.new_id(), "title": title, "icon": "",
                    "scope": parent["scope"], "ext_filter": list(parent["ext_filter"]),
                    "hive": parent["hive"], "extended": False, "position": "default",
                    "action": {"kind": parent["action"]["kind"], "target": target,
                               "args": parent["action"]["args"], "workdir": ""},
                    "children": []}
        dom = deepcopy(original)
        dom["title"] = title
        action = dom.get("action") if isinstance(dom.get("action"), dict) else {}
        action["target"] = target
        dom["action"] = {"kind": "program", "target": "", "args": "", "workdir": ""} | action
        # 半截导入的子项可能缺键 / 类型不符：补默认值，而不是让它带着畸形值进 save_item
        for key, default in (("id", ident), ("icon", ""), ("scope", "file"),
                             ("ext_filter", []), ("hive", "hkcu"), ("extended", False),
                             ("position", "default"), ("children", [])):
            if not isinstance(dom.get(key), type(default)):
                dom[key] = deepcopy(default)
        return dom

    # ── 取值 / 校验 ─────────────────────────────────────────────
    def value(self):
        """当前控件 → 完整 DOM dict（可直接喂 `validate_item` / `save_item`）。

        `hive` 取 `self._hive`（**原样保留**，见 `custom_rows.hive_of`）。"""
        rows = self._rows
        dom = {"id": self._id, "title": self.title_edit.text().strip(),
               "icon": self.icon_edit.text().strip(),
               "scope": rows.scope_value(self.scope_combo.currentIndex()),
               "ext_filter": rows.parse_ext_filter(self.ext_edit.text()),
               "hive": self._hive, "extended": bool(self.extended_box.isChecked()),
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
