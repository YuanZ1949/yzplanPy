"""RSS 对话框 F：新增/编辑聚合。"""
import json
import logging
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from ..styles import _btn_primary_style, _btn_style
from ..text_utils import _extract_keywords, _parse_keywords, rss_palette
from ..utils import _bind_geometry, _decode_feed_icon
from core.theme.tokens import sizing
from ui.widgets import make_label
from .builders import (_HighFreqMixin, build_high_freq_group,
                       build_keyword_group, build_members_group, build_tag_group)
logger = logging.getLogger("rss_aggregator")
_TYPE_LABELS = {"mixed": "混合", "keyword": "关键词", "torrent": "磁链 Hash", "similarity": "相似性", "remainder": "未分类条目"}
_HINTS = {
    "mixed": "保留成员内全部已入库条目（可用过滤进一步筛选）。",
    "keyword": "必须∩可选∖禁止：每词命中标题或描述。",
    "torrent": "按 torrent_hash 分组折叠，点开查看成员条目。",
    "similarity": "按条目标题相似度分组折叠，点开查看相似条目。",
    "remainder": "未分类条目：父聚合中未被任何子聚合命中的条目。",
}

class _AddAggregationDialog(QtWidgets.QDialog, _HighFreqMixin):
    """新建/编辑手动聚合：勾选成员（订阅源/标签），选处理类型，配置关键词三桶。

    parent 模式（parent_id>0）：继承父聚合快照，不选成员，支持自动提取关键词与相似度阈值。
    """

    TYPE_LABELS = _TYPE_LABELS

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
        self._type_keys = []
        for key, label in _TYPE_LABELS.items():
            if self._parent_mode and key == "remainder":
                continue
            self._type_keys.append(key)
            self.combo_type.addItem(label, key)
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
        info.setStyleSheet(f"QLabel {{ color:{rss_palette()['rss_text_secondary']}; font-size:{sizing()['rss_font_md']}px; }}")
        lay.addWidget(info)
        self.lb_hint = QtWidgets.QLabel("")
        self.lb_hint.setWordWrap(True)
        self.lb_hint.setStyleSheet(f"QLabel {{ color:{rss_palette()['rss_text_faint']}; font-size:{sizing()['rss_font_md']}px; }}")
        lay.addWidget(self.lb_hint)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

        # 成员勾选（非 parent 模式）或只读说明（parent 模式）
        if self._parent_mode:
            parent_name = self._parent_agg["name"] if self._parent_agg else "父聚合"
            parent_count = self.store.get_aggregation_item_count(effective_parent_id)
            lbl = QtWidgets.QLabel(f"成员：继承父聚合快照「{parent_name}」（{parent_count} 条）")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"QLabel {{ color:{rss_palette()['rss_text_secondary']}; font-size:{sizing()['rss_font_md']}px; padding:{sizing()['rss_hint_padding']}; }}")
            lay.addWidget(lbl)
            self.member_list = None
        else:
            lay.addWidget(build_members_group(self))
            lay.addWidget(build_tag_group(self))
            # 初始可见性：相似性类型才显示标签组，其他显示成员组
            _is_sim = self.combo_type.currentData() == "similarity"
            self._tag_group.setVisible(_is_sim)
            self._members_group.setVisible(not _is_sim)

        # 关键词三桶 + 自动提取按钮
        lay.addWidget(build_keyword_group(self))
        self.hf_group = build_high_freq_group(self, self)
        lay.addWidget(self.hf_group)

        # 相似度阈值（仅 parent 模式）
        if self._parent_mode:
            self.spin_threshold = QtWidgets.QDoubleSpinBox()
            self.spin_threshold.setRange(0.10, 0.99)
            self.spin_threshold.setSingleStep(0.05)
            self.spin_threshold.setDecimals(2)
            self.spin_threshold.setSuffix(" 相似度")
            self.spin_threshold.setValue(self.agg.get("similarity_threshold") if self.agg else 0.55)
            self.spin_threshold.setVisible(self.combo_type.currentData() == "similarity")
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
        self.btn_auto_extract.setVisible(self.combo_type.currentData() == "similarity")

        # 命中预览 S1：底部实时命中数（300ms 防抖）
        self._hit_label = make_label("当前条件命中 — 条")
        lay.addWidget(self._hit_label)
        self._hit_timer = QtCore.QTimer(self)
        self._hit_timer.setSingleShot(True)
        self._hit_timer.setInterval(300)
        self._hit_timer.timeout.connect(self._update_hit_count)
        self.combo_type.currentIndexChanged.connect(lambda _i: self._hit_timer.start())
        for edit in (self.in_required, self.in_optional, self.in_forbidden):
            edit.textChanged.connect(lambda _t: self._hit_timer.start())
        self._hit_timer.start()

    def _load_members(self):
        if self.member_list is None:
            return
        self.member_items = []
        self.member_list.clear()
        prev_feed_ids = set(json.loads(self.agg.get("feed_ids") or "[]")) if self.agg else set()
        prev_tags = set(json.loads(self.agg.get("tags") or "[]")) if self.agg else set()
        for f in self.store.list_feeds():
            item = QtWidgets.QListWidgetItem(f"订阅源: {f['name']}")
            icon = _decode_feed_icon(f.get("icon") or "")
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
        if hasattr(self, "tag_list"):
            prev_tags = set(json.loads(self.agg.get("tags") or "[]"))
            for i in range(self.tag_list.count()):
                if self.tag_list.item(i).text() in prev_tags:
                    self.tag_list.item(i).setSelected(True)

    def _on_type_changed(self):
        k = self.combo_type.currentData()
        self.lb_hint.setText(_HINTS.get(k, ""))
        if self._parent_mode and hasattr(self, "spin_threshold"):
            self.spin_threshold.setVisible(k == "similarity")
        for attr, vis in (("_tag_group", k == "similarity"),
                           ("_members_group", k != "similarity"),
                           ("btn_auto_extract", k == "similarity")):
            if hasattr(self, attr):
                getattr(self, attr).setVisible(vis)

    def _collect_agg_dict(self):
        """收集当前表单状态为聚合 dict（供命中预览 count_aggregation_hits 使用）。"""
        agg_type = self.combo_type.currentData() or "mixed"
        feed_ids, tags = [], []
        if self._parent_mode and self._parent_agg:
            feed_ids = json.loads(self._parent_agg.get("feed_ids") or "[]")
            tags = json.loads(self._parent_agg.get("tags") or "[]")
        elif agg_type == "similarity" and hasattr(self, "tag_list"):
            tags = [item.text() for item in self.tag_list.selectedItems()]
        elif self.member_list is not None:
            for i in range(self.member_list.count()):
                it = self.member_list.item(i)
                if it.checkState() == QtCore.Qt.Checked:
                    kind, val = it.data(QtCore.Qt.UserRole)
                    (feed_ids if kind == "feed" else tags).append(val)
        return {
            "agg_type": agg_type,
            "feed_ids": feed_ids,
            "tags": tags,
            "kw_required": _parse_keywords(self.in_required.text()),
            "kw_optional": _parse_keywords(self.in_optional.text()),
            "kw_forbidden": _parse_keywords(self.in_forbidden.text()),
        }

    def _update_hit_count(self):
        """防抖后刷新命中预览 label。"""
        store = getattr(self.owner, "store", None)
        if store is None or not hasattr(store, "count_aggregation_hits"):
            return
        try:
            count = store.count_aggregation_hits(self._collect_agg_dict())
        except Exception:
            count = 0
        self._hit_label.setText(f"当前条件命中 {count} 条")

    def _on_auto_extract(self):
        """自动提取关键词：从成员标题中高频词填入必须关键词桶。"""
        titles = []
        if self._parent_agg:
            titles = self.store.aggregation_titles(self._parent_agg["id"])
        elif hasattr(self, "tag_list") and self.combo_type.currentData() == "similarity":
            selected = [item.text() for item in self.tag_list.selectedItems()]
            recent_fn = getattr(self.store, "recent", None)
            if callable(recent_fn) and selected:
                titles = [it.get("title") or "" for it in recent_fn(limit=200, tags=selected)]
        if not titles:
            return
        self.in_required.setText(" ".join(_extract_keywords(titles)))
        self.in_optional.setText("")
        self.in_forbidden.setText("")

    def _on_ok(self):
        name = self.in_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "提示", "请填写聚合名称")
            return
        agg_type = self.combo_type.currentData()
        feed_ids, tags = [], []
        if not self._parent_mode:
            if agg_type == "similarity" and hasattr(self, "tag_list"):
                tags = [item.text() for item in self.tag_list.selectedItems()]
            elif self.member_list is not None:
                for i in range(self.member_list.count()):
                    it = self.member_list.item(i)
                    if it.checkState() == QtCore.Qt.Checked:
                        kind, val = it.data(QtCore.Qt.UserRole)
                        (feed_ids if kind == "feed" else tags).append(val)
            if not feed_ids and not tags:
                QtWidgets.QMessageBox.warning(self, "提示", "请至少选择一个成员（订阅源或标签）")
                return
        kw_required = _parse_keywords(self.in_required.text())
        kw_optional = _parse_keywords(self.in_optional.text())
        kw_forbidden = _parse_keywords(self.in_forbidden.text())
        if agg_type == "keyword" and not kw_required and not kw_optional:
            QtWidgets.QMessageBox.warning(self, "提示", "关键词类型至少需要【必须】或【可选】其一")
            return
        parent_id = self._parent_agg["id"] if (self._parent_mode and self._parent_agg) else 0
        base = dict(agg_type=agg_type, kw_required=kw_required,
                    kw_optional=kw_optional, kw_forbidden=kw_forbidden)
        if self.agg_id:
            if self._parent_mode:
                if agg_type == "similarity":
                    base["similarity_threshold"] = self.spin_threshold.value()
                self.store.update_aggregation(self.agg_id, name=name, parent_id=parent_id, **base)
            else:
                self.store.update_aggregation(self.agg_id, name=name, feed_ids=feed_ids, tags=tags, **base)
            self.store.refresh_aggregation(self.agg_id)
        else:
            if self._parent_mode and agg_type == "similarity":
                new_id = self.store.add_aggregation(
                    name, parent_id=parent_id,
                    similarity_threshold=self.spin_threshold.value(), **base)
            else:
                new_id = self.store.add_aggregation(
                    name, feed_ids=feed_ids, tags=tags, parent_id=parent_id, **base)
            self.store.refresh_aggregation(new_id)
        self.accept()
