"""RSS 对话框 E：过滤规则/关键词/分类编辑。"""

import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .utils import _bind_geometry

logger = logging.getLogger("rss_aggregator")

class _FilterRuleDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加过滤规则")
        self.setMinimumWidth(400)
        _bind_geometry(self, "rss_filter_rule")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("规则名称")
        self.combo_field = QtWidgets.QComboBox()
        self.combo_field.addItems(["标题", "描述", "链接"])
        self.combo_operator = QtWidgets.QComboBox()
        self.combo_operator.addItems(["包含", "不包含", "等于", "开头是", "结尾是", "正则"])
        self.in_value = QtWidgets.QLineEdit()
        self.in_value.setPlaceholderText("匹配值")
        self.combo_action = QtWidgets.QComboBox()
        self.combo_action.addItems(["添加标签", "跳过", "高亮"])
        self.in_action_value = QtWidgets.QLineEdit()
        self.in_action_value.setPlaceholderText("标签名称（添加标签时填写）")
        form.addRow("名称", self.in_name)
        form.addRow("字段", self.combo_field)
        form.addRow("条件", self.combo_operator)
        form.addRow("值", self.in_value)
        form.addRow("动作", self.combo_action)
        form.addRow("动作值", self.in_action_value)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        name = self.in_name.text().strip()
        field_map = {"标题": "title", "描述": "description", "链接": "link"}
        op_map = {"包含": "contains", "不包含": "not_contains", "等于": "equals", "开头是": "starts_with", "结尾是": "ends_with", "正则": "regex"}
        action_map = {"添加标签": "tag", "跳过": "skip", "高亮": "highlight"}
        field = field_map.get(self.combo_field.currentText(), "title")
        operator = op_map.get(self.combo_operator.currentText(), "contains")
        value = self.in_value.text().strip()
        action = action_map.get(self.combo_action.currentText(), "tag")
        action_value = self.in_action_value.text().strip()
        if not name or not value:
            return
        self.owner.store.add_filter_rule(name, field, operator, value, action, action_value)
        self.accept()


class _KeywordDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加关键词")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_keyword")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_keyword = QtWidgets.QLineEdit()
        self.in_keyword.setPlaceholderText("关键词")
        self.in_color = QtWidgets.QLineEdit()
        self.in_color.setText("#ff6b6b")
        self.chk_notify = QtWidgets.QCheckBox("匹配时通知")
        self.chk_notify.setChecked(True)
        form.addRow("关键词", self.in_keyword)
        form.addRow("颜色", self.in_color)
        form.addRow("", self.chk_notify)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        keyword = self.in_keyword.text().strip()
        color = self.in_color.text().strip() or "#ff6b6b"
        notify = 1 if self.chk_notify.isChecked() else 0
        if not keyword:
            return
        self.owner.store.add_keyword(keyword, color, notify)
        self.accept()


class _CategoryDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None, category=None):
        super().__init__(parent)
        self.setWindowTitle("编辑分类" if category else "添加分类")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_category")
        self.owner = owner
        self.category = category

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit(category.get("name", "") if category else "")
        self.in_color = QtWidgets.QLineEdit(category.get("color", "#1a73e8") if category else "#1a73e8")
        form.addRow("名称", self.in_name)
        form.addRow("颜色", self.in_color)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("保存")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_save(self):
        name = self.in_name.text().strip()
        color = self.in_color.text().strip() or "#1a73e8"
        if not name:
            return
        if self.category:
            self.owner.store.update_category(self.category["id"], name=name, color=color)
        else:
            self.owner.store.add_category(name, color)
        self.accept()
