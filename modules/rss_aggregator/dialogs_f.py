"""RSS 对话框 F：新增/编辑聚合。"""

import json
import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .styles import _btn_primary_style, _btn_style, _rss_head_style
from .text_utils import _extract_keywords, _parse_keywords, _rss_colors
from .utils import _bind_geometry, _decode_feed_icon

logger = logging.getLogger("rss_aggregator")

class _AddAggregationDialog(QtWidgets.QDialog):
    """新建/编辑手动聚合：勾选成员（订阅源/标签），选处理类型，配置关键词三桶。

    parent 模式（parent_id>0）：继承父聚合快照，不选成员，支持自动提取关键词与相似度阈值。
    """

    TYPE_LABELS = {"mixed": "混合", "keyword": "关键词", "torrent": "磁链 Hash", "similarity": "相似性"}

    def __init__(self, owner, page, agg_id=None, parent=None, parent_id=0):
        super().__init__(parent)
        self.owner = owner
        self.page = page
        self.store = owner.store
        self.agg_id = agg_id
        self.agg = self.store.get_aggregation(agg_id) if agg_id else None

        # parent 模式：新建子聚合 或 编辑已有子聚合
        effective_parent_id = parent_id or (self.agg or {}).get("parent_id") or 0
        self._parent_agg = self.store.get_aggregation(effective_parent_id) if effective_parent_id else None
        self._parent_mode = parent_id > 0 or (self.agg and self.agg.get("parent_id", 0) > 0)

        if self._parent_mode:
            self.setWindowTitle("编辑二级条目" if self.agg else "新建二级条目")
        else:
            self.setWindowTitle("编辑聚合" if self.agg else "新建聚合")
        self.setMinimumWidth(520)
        _bind_geometry(self, "rss_agg_dialog")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit((self.agg or {}).get("name", ""))
        self.in_name.setPlaceholderText("聚合名称（必填）")
        form.addRow("名称", self.in_name)

        self.combo_type = QtWidgets.QComboBox()
        if self._parent_mode:
            self._type_keys = ["keyword", "similarity"]
        else:
            self._type_keys = ["mixed", "keyword", "torrent", "similarity"]
        for k in self._type_keys:
            self.combo_type.addItem(self.TYPE_LABELS[k], k)
        cur_type = (self.agg or {}).get("agg_type") or ("keyword" if self._parent_mode else "mixed")
        if cur_type in self._type_keys:
            self.combo_type.setCurrentIndex(self._type_keys.index(cur_type))
        form.addRow("处理类型", self.combo_type)
        lay.addLayout(form)

        info = QtWidgets.QLabel(
            "混合：直接聚合成员条目；关键词：仅保留命中【必须】且【可选>1】且避开【禁止】的条目；"
            "磁链Hash：按 torrent_hash 折叠展示（保存时先快照）；"
            "相似性：按条目标题相似度折叠为二级分组（保存时先快照）。")
        info.setWordWrap(True)
        info.setStyleSheet(f"QLabel {{ color:{_rss_colors()['text_secondary']}; font-size:12px; }}")
        lay.addWidget(info)

        # 处理类型说明随类型变化
        self.lb_hint = QtWidgets.QLabel("")
        self.lb_hint.setWordWrap(True)
        self.lb_hint.setStyleSheet(f"QLabel {{ color:{_rss_colors()['text_faint']}; font-size:12px; }}")
        lay.addWidget(self.lb_hint)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

        # 成员勾选（非 parent 模式）或只读说明（parent 模式）
        if self._parent_mode:
            parent_name = self._parent_agg["name"] if self._parent_agg else "父聚合"
            parent_count = self.store.get_aggregation_item_count(effective_parent_id)
            lbl_members = QtWidgets.QLabel(
                f"成员：继承父聚合快照「{parent_name}」（{parent_count} 条）")
            lbl_members.setWordWrap(True)
            lbl_members.setStyleSheet(
                f"QLabel {{ color:{_rss_colors()['text_secondary']}; font-size:12px; padding: 8px 4px; }}")
            lay.addWidget(lbl_members)
            self.member_list = None
        else:
            members_group = QtWidgets.QGroupBox("成员")
            members_group.setStyleSheet(_rss_head_style())
            mg = QtWidgets.QVBoxLayout(members_group)
            self.member_list = QtWidgets.QListWidget()
            self.member_list.setMaximumHeight(160)
            self._load_members()
            mg.addWidget(self.member_list)
            lay.addWidget(members_group)

        # 关键词三桶
        kw_group = QtWidgets.QGroupBox("关键词三桶（仅关键词类型）")
        kw_group.setStyleSheet(_rss_head_style())
        kg = QtWidgets.QVBoxLayout(kw_group)

        # keyword 类型 + parent 模式：标题行加「自动提取关键词」按钮
        if self._parent_mode:
            kw_title_row = QtWidgets.QHBoxLayout()
            kw_title_lbl = QtWidgets.QLabel(kw_group.title())
            kw_title_row.addWidget(kw_title_lbl)
            kw_title_row.addStretch(1)
            self.btn_auto_extract = QtWidgets.QPushButton("自动提取关键词")
            self.btn_auto_extract.setStyleSheet(_btn_style(min_width=80))
            self.btn_auto_extract.clicked.connect(self._on_auto_extract)
            kw_title_row.addWidget(self.btn_auto_extract)
            kg.addLayout(kw_title_row)

        formk = QtWidgets.QFormLayout()
        self.in_required = QtWidgets.QLineEdit()
        self.in_required.setPlaceholderText("必须命中（每词都需命中，逗号/空格分隔）")
        self.in_optional = QtWidgets.QLineEdit()
        self.in_optional.setPlaceholderText("可选命中（至少一词，空=不限）")
        self.in_forbidden = QtWidgets.QLineEdit()
        self.in_forbidden.setPlaceholderText("禁止命中（每词都不得命中）")
        formk.addRow("必须", self.in_required)
        formk.addRow("可选", self.in_optional)
        formk.addRow("禁止", self.in_forbidden)
        kg.addLayout(formk)
        lay.addWidget(kw_group)

        # 相似度阈值（仅 parent 模式）
        if self._parent_mode:
            self.spin_threshold = QtWidgets.QDoubleSpinBox()
            self.spin_threshold.setRange(0.10, 0.99)
            self.spin_threshold.setSingleStep(0.05)
            self.spin_threshold.setDecimals(2)
            self.spin_threshold.setSuffix(" 相似度")
            self.spin_threshold.setValue(
                self.agg.get("similarity_threshold") if self.agg else 0.55)
            self.spin_threshold.setVisible(
                self.combo_type.currentData() == "similarity")
            lay.addWidget(self.spin_threshold)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.setStyleSheet(_btn_style(min_width=80))
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QtWidgets.QPushButton("保存")
        self.btn_ok.setStyleSheet(_btn_primary_style(min_width=80))
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        lay.addLayout(btn_row)

        self._fill_existing()

    def _load_members(self):
        if self.member_list is None:
            return
        self.member_items = []
        self.member_list.clear()
        if self.agg:
            prev_feed_ids = set(json.loads(self.agg.get("feed_ids") or "[]"))
            prev_tags = set(json.loads(self.agg.get("tags") or "[]"))
        else:
            prev_feed_ids = set()
            prev_tags = set()

        def feed_icon(feed):
            return _decode_feed_icon(feed.get("icon") or "")

        for f in self.store.list_feeds():
            icon = feed_icon(f)
            item = QtWidgets.QListWidgetItem(f"订阅源: {f['name']}")
            if icon:
                item.setIcon(icon)
            item.setData(QtCore.Qt.UserRole, ("feed", f["id"]))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if f["id"] in prev_feed_ids else QtCore.Qt.Unchecked)
            self.member_list.addItem(item)
            self.member_items.append(("feed", f["id"]))

        for tag in self.store.list_tags():
            item = QtWidgets.QListWidgetItem(f"标签: {tag}")
            item.setData(QtCore.Qt.UserRole, ("tag", tag))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if tag in prev_tags else QtCore.Qt.Unchecked)
            self.member_list.addItem(item)
            self.member_items.append(("tag", tag))

    def _fill_existing(self):
        if not self.agg:
            return
        self.in_required.setText(" ".join(json.loads(self.agg.get("kw_required") or "[]")))
        self.in_optional.setText(" ".join(json.loads(self.agg.get("kw_optional") or "[]")))
        self.in_forbidden.setText(" ".join(json.loads(self.agg.get("kw_forbidden") or "[]")))

    def _on_type_changed(self):
        k = self.combo_type.currentData()
        hint = {
            "mixed": "保留成员内全部已入库条目（可用过滤进一步筛选）。",
            "keyword": "必须∩可选∖禁止：每词命中标题或描述。",
            "torrent": "按 torrent_hash 分组折叠，点开查看成员条目。",
            "similarity": "按条目标题相似度分组折叠，点开查看相似条目。",
        }.get(k, "")
        self.lb_hint.setText(hint)
        # parent 模式下控制相似度阈值可见性（spin_threshold 可能尚未创建）
        if self._parent_mode and hasattr(self, "spin_threshold"):
            self.spin_threshold.setVisible(k == "similarity")

    def _on_auto_extract(self):
        """自动提取关键词：从父聚合快照标题中高频词填入必须关键词桶。"""
        if not self._parent_agg:
            return
        titles = self.store.aggregation_titles(self._parent_agg["id"])
        keywords = _extract_keywords(titles)
        self.in_required.setText(" ".join(keywords))
        self.in_optional.setText("")
        self.in_forbidden.setText("")

    def _on_ok(self):
        name = self.in_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "提示", "请填写聚合名称")
            return
        agg_type = self.combo_type.currentData()

        # ── 成员收集（仅非 parent 模式）──
        feed_ids = []
        tags = []
        if self.member_list is not None:
            for i in range(self.member_list.count()):
                it = self.member_list.item(i)
                if it.checkState() == QtCore.Qt.Checked:
                    kind, val = it.data(QtCore.Qt.UserRole)
                    if kind == "feed":
                        feed_ids.append(val)
                    else:
                        tags.append(val)
            if not feed_ids and not tags:
                QtWidgets.QMessageBox.warning(self, "提示", "请至少勾选一个成员（订阅源或标签）")
                return

        kw_required = _parse_keywords(self.in_required.text())
        kw_optional = _parse_keywords(self.in_optional.text())
        kw_forbidden = _parse_keywords(self.in_forbidden.text())
        if agg_type == "keyword" and not kw_required and not kw_optional:
            QtWidgets.QMessageBox.warning(self, "提示", "关键词类型至少需要【必须】或【可选】其一")
            return

        # parent 模式的 parent_id
        parent_id = 0
        if self._parent_mode and self._parent_agg:
            parent_id = self._parent_agg["id"]

        if self.agg_id:
            if self._parent_mode:
                kwargs = dict(
                    name=name, agg_type=agg_type,
                    kw_required=kw_required, kw_optional=kw_optional,
                    kw_forbidden=kw_forbidden, parent_id=parent_id)
                if agg_type == "similarity":
                    kwargs["similarity_threshold"] = self.spin_threshold.value()
                self.store.update_aggregation(self.agg_id, **kwargs)
            else:
                self.store.update_aggregation(
                    self.agg_id, name=name, agg_type=agg_type,
                    feed_ids=feed_ids, tags=tags,
                    kw_required=kw_required, kw_optional=kw_optional,
                    kw_forbidden=kw_forbidden)
            self.store.refresh_aggregation(self.agg_id)
        else:
            if self._parent_mode and agg_type == "similarity":
                new_id = self.store.add_aggregation(
                    name, agg_type=agg_type, parent_id=parent_id,
                    kw_required=kw_required, kw_optional=kw_optional,
                    kw_forbidden=kw_forbidden,
                    similarity_threshold=self.spin_threshold.value())
            else:
                new_id = self.store.add_aggregation(
                    name, agg_type=agg_type, feed_ids=feed_ids, tags=tags,
                    kw_required=kw_required, kw_optional=kw_optional,
                    kw_forbidden=kw_forbidden,
                    parent_id=parent_id)
            self.store.refresh_aggregation(new_id)
        self.accept()
