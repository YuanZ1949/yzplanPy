"""_AddAggregationDialog parent 模式测试。

离屏运行（QT_QPA_PLATFORM=offscreen），替身 store 记录调用。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from unittest.mock import MagicMock, patch, call

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtWidgets import QApplication

# ── App 实例 ──────────────────────────────────────────────
app = QApplication.instance() or QApplication([])


# ── 替身 Store ────────────────────────────────────────────

class _StubStore:
    """最小化替身 store，记录 add_aggregation / update_aggregation 的调用参数。"""

    def __init__(self):
        self._aggs = {}          # id -> dict
        self._next_id = 1
        self._feeds = []
        self._tags = []
        self.add_calls = []
        self.update_calls = []
        self.refresh_calls = []
        self.titles_for = {}     # agg_id -> [title, ...]
        self.item_counts = {}    # agg_id -> int

    # ── 聚合 ──

    def get_aggregation(self, agg_id):
        return self._aggs.get(agg_id)

    def add_aggregation(self, name, agg_type="mixed", feed_ids=None, tags=None,
                        kw_required=None, kw_optional=None, kw_forbidden=None,
                        sort_order=0, parent_id=0, similarity_threshold=0.55,
                        similarity_granularity=1):
        nid = self._next_id
        self._next_id += 1
        rec = {
            "id": nid, "name": name, "agg_type": agg_type,
            "feed_ids": str(feed_ids or []), "tags": str(tags or []),
            "kw_required": str(kw_required or []), "kw_optional": str(kw_optional or []),
            "kw_forbidden": str(kw_forbidden or []),
            "parent_id": parent_id, "similarity_threshold": similarity_threshold,
            "similarity_granularity": similarity_granularity,
        }
        self._aggs[nid] = rec
        self.add_calls.append({
            "name": name, "agg_type": agg_type,
            "feed_ids": feed_ids, "tags": tags,
            "kw_required": kw_required, "kw_optional": kw_optional,
            "kw_forbidden": kw_forbidden,
            "parent_id": parent_id,
            "similarity_threshold": similarity_threshold,
            "similarity_granularity": similarity_granularity,
        })
        return nid

    def update_aggregation(self, agg_id, **kwargs):
        self.update_calls.append({"agg_id": agg_id, **kwargs})

    def refresh_aggregation(self, agg_id):
        self.refresh_calls.append(agg_id)

    def aggregation_titles(self, agg_id):
        return self.titles_for.get(agg_id, [])

    def get_aggregation_item_count(self, agg_id):
        return self.item_counts.get(agg_id, 0)

    # ── 成员（非 parent 模式用）──

    def list_feeds(self):
        return self._feeds

    def list_tags(self):
        return self._tags


# ── Helpers ──────────────────────────────────────────────

def _make_parent(store, name="ParentMix", parent_id=1):
    """创建并注册一条父聚合记录。"""
    rec = {
        "id": parent_id, "name": name, "agg_type": "mixed",
        "feed_ids": "[1,2]", "tags": "[]",
        "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
        "parent_id": 0, "similarity_threshold": 0.55,
        "similarity_granularity": 1,
    }
    store._aggs[parent_id] = rec
    return rec


def _make_child(store, parent_id=1, agg_id=10, name="ChildKey",
                agg_type="keyword", similarity_threshold=0.55,
                similarity_granularity=1):
    """创建并注册一条子聚合记录。"""
    rec = {
        "id": agg_id, "name": name, "agg_type": agg_type,
        "feed_ids": "[]", "tags": "[]",
        "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
        "parent_id": parent_id, "similarity_threshold": similarity_threshold,
        "similarity_granularity": similarity_granularity,
    }
    store._aggs[agg_id] = rec
    return rec


# ── Tests ────────────────────────────────────────────────

@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_new_type_combo_2_items(mock_bg):
    """parent 模式下类型下拉仅 keyword + similarity 两项。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])

    assert dlg.combo_type.count() == 2
    keys = [dlg.combo_type.itemData(i) for i in range(2)]
    assert keys == ["keyword", "similarity"]


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_no_member_list(mock_bg):
    """parent 模式下 member_list 为 None。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    assert dlg.member_list is None


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_auto_extract_button(mock_bg):
    """parent 模式下自动提取按钮存在，点击后 store.aggregation_titles 被调用并填充 in_required。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)
    store.titles_for[1] = ["AI Trend 2026", "AI in Healthcare", "Python Tips"]

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])

    assert hasattr(dlg, "btn_auto_extract")
    # 模拟点击
    dlg._on_auto_extract()
    assert store.titles_for[1]  # sanity
    # in_required 应被填充（ai 和 healthcare 是高频词）
    text = dlg.in_required.text().strip()
    assert len(text) > 0, "自动提取后 in_required 应非空"
    assert "ai" in text.lower(), f"in_required 应包含 'ai': {text}"
    # optional / forbidden 被清空
    assert dlg.in_optional.text() == ""
    assert dlg.in_forbidden.text() == ""


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_spin_threshold_default_055(mock_bg):
    """similarity 类型下 spin_threshold 可见且默认 0.55。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    # 默认类型 keyword → spin 被隐藏
    assert dlg.spin_threshold.isHidden()

    # 切换到 similarity → spin 不再被隐藏（isVisible 要求父窗口 show，用 not isHidden 代替）
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    assert not dlg.spin_threshold.isHidden()
    assert dlg.spin_threshold.value() == pytest.approx(0.55)


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_save_add_keyword(mock_bg):
    """parent 模式 keyword 类型：add 调用含 parent_id，不含 similarity_threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)
    store.item_counts[1] = 42

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])
    dlg.in_name.setText("TestKeyword")
    # keyword 类型是默认的
    assert dlg.combo_type.currentData() == "keyword"
    dlg.in_required.setText("AI Python")

    # 点保存
    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["name"] == "TestKeyword"
    assert c["agg_type"] == "keyword"
    assert c["parent_id"] == 1
    # keyword 类型不传 similarity_threshold（保留默认 0.55）
    assert c["similarity_threshold"] == 0.55


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_save_add_similarity(mock_bg):
    """parent 模式 similarity 类型：add 调用含 parent_id 与自定义 threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    parent_rec = _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=parent_rec["id"])
    dlg.in_name.setText("TestSimilarity")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    dlg.spin_threshold.setValue(0.70)

    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["name"] == "TestSimilarity"
    assert c["agg_type"] == "similarity"
    assert c["parent_id"] == 1
    assert c["similarity_threshold"] == 0.70


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_window_title(mock_bg):
    """parent 模式窗口标题。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    assert dlg.windowTitle() == "新建二级条目"

    # 编辑模式
    child = _make_child(store, parent_id=1, agg_id=10)
    dlg2 = _AddAggregationDialog(owner, MagicMock(), agg_id=10)
    assert dlg2.windowTitle() == "编辑二级条目"


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_mode_requires_members(mock_bg):
    """顶层模式（非 parent）仍要求成员。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    dlg.in_name.setText("TopLevelAgg")

    # 没有成员 → _on_ok 会发 warning（QMessageBox），但在 offscreen 下我们检查 call
    # store 应没有 add 调用
    with patch("modules.rss_aggregator.dialogs.f.QtWidgets.QMessageBox"):
        dlg._on_ok()
    assert len(store.add_calls) == 0, "无成员时不应调用 add_aggregation"


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_mode_4_type_items(mock_bg):
    """非 parent 模式下类型下拉有 4 项。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    assert dlg.combo_type.count() == 4


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_top_level_mode_has_member_list(mock_bg):
    """非 parent 模式下 member_list 是 QListWidget。"""
    from PySide6.QtWidgets import QListWidget
    store = _StubStore()
    owner = MagicMock()
    owner.store = store

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock())
    assert isinstance(dlg.member_list, QListWidget)


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_edit_existing_passes_parent_id_and_threshold(mock_bg):
    """编辑已有子聚合时，update 调用含 parent_id 与 similarity_threshold。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store, parent_id=5, name="BigParent")
    _make_child(store, parent_id=5, agg_id=20, name="OldChild",
                agg_type="similarity", similarity_threshold=0.80)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), agg_id=20)
    dlg.in_name.setText("RenamedChild")
    # similarity 类型应已选中
    dlg.spin_threshold.setValue(0.60)

    dlg._on_ok()

    assert len(store.update_calls) == 1
    u = store.update_calls[0]
    assert u["agg_id"] == 20
    assert u["parent_id"] == 5
    assert u["similarity_threshold"] == 0.60
    # 不应包含 feed_ids / tags（parent 模式不收集成员）
    assert "feed_ids" not in u
    assert "tags" not in u


# ── 粒度滑块 Tests ──────────────────────────────────────

@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_spin_granularity_exists_with_correct_range(mock_bg):
    """similarity 类型下 spin_granularity 存在、范围 [1,10]、默认 1。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    assert hasattr(dlg, "spin_granularity")
    assert dlg.spin_granularity.minimum() == 1
    assert dlg.spin_granularity.maximum() == 10
    assert dlg.spin_granularity.value() == 1


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_granularity_visibility_toggles(mock_bg):
    """granularity 控件在 keyword 时隐藏、similarity 时显示。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    # 默认 keyword → hidden
    assert dlg.spin_granularity.isHidden()
    assert dlg._granularity_label.isHidden()

    # 切到 similarity → shown
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    assert not dlg.spin_granularity.isHidden()
    assert not dlg._granularity_label.isHidden()

    # 切回 keyword → hidden
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("keyword"))
    assert dlg.spin_granularity.isHidden()
    assert dlg._granularity_label.isHidden()


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_save_add_similarity_passes_granularity(mock_bg):
    """similarity 创建保存时 add 调用含 similarity_granularity。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    dlg.in_name.setText("SimGranular")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    dlg.spin_granularity.setValue(5)

    dlg._on_ok()

    assert len(store.add_calls) == 1
    c = store.add_calls[0]
    assert c["similarity_granularity"] == 5


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_edit_existing_backfills_granularity(mock_bg):
    """编辑已有子聚合时 granularity 从存储值回填。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store, parent_id=5)
    _make_child(store, parent_id=5, agg_id=20, name="OldChild",
                agg_type="similarity", similarity_threshold=0.80,
                similarity_granularity=7)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), agg_id=20)

    assert dlg.spin_granularity.value() == 7


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_edit_existing_update_passes_granularity(mock_bg):
    """编辑已有子聚合保存时 update 调用含 similarity_granularity。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store, parent_id=5)
    _make_child(store, parent_id=5, agg_id=20, name="OldChild",
                agg_type="similarity", similarity_threshold=0.80,
                similarity_granularity=3)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), agg_id=20)
    dlg.in_name.setText("RenamedChild")
    dlg.spin_granularity.setValue(9)

    dlg._on_ok()

    assert len(store.update_calls) == 1
    u = store.update_calls[0]
    assert u["similarity_granularity"] == 9


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
@patch("modules.rss_aggregator.dialogs.f._cluster_by_similarity")
def test_update_threshold_preview_passes_granularity(mock_cluster, mock_bg):
    """_update_threshold_preview 将 granularity 传给 _cluster_by_similarity。"""
    mock_cluster.return_value = []
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)
    store.get_all_aggregation_torrent_items = MagicMock(return_value={})

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    dlg.spin_threshold.setValue(0.65)
    dlg.spin_granularity.setValue(4)

    dlg._update_threshold_preview()

    mock_cluster.assert_called_once()
    args = mock_cluster.call_args
    assert args[0][1] == 0.65  # threshold
    assert args[0][2] == 4     # granularity


# ── Todo 19：粒度初值来自 config 共享默认 ────────────────────

class _FakeConfig:
    """dict-backed config 替身：记录 get/set。"""

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_new_dialog_granularity_initial_from_config(mock_bg):
    """新建相似性聚合时粒度初值来自 config 的 rss.similarity_granularity。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    owner.context.config = _FakeConfig({"rss.similarity_granularity": 5})
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    assert dlg.spin_granularity.value() == 5


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
@pytest.mark.parametrize("cfg_value", [None, 0, 99])
def test_new_dialog_granularity_invalid_config_falls_back(mock_bg, cfg_value):
    """config 缺失该 key 或值非法（0/99）时回退默认 1 且不抛。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    data = {} if cfg_value is None else {"rss.similarity_granularity": cfg_value}
    owner.context.config = _FakeConfig(data)
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    assert dlg.spin_granularity.value() == 1


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_save_writes_granularity_back_to_config(mock_bg):
    """保存 similarity 聚合时把粒度写回 config 默认。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    owner.context.config = _FakeConfig()
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    dlg.in_name.setText("SimGran")
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))
    dlg.spin_granularity.setValue(6)

    dlg._on_ok()

    assert owner.context.config.data["rss.similarity_granularity"] == 6


# ── Todo 25：粒度控件文案 = 相似度比较粒度 ──────────────────

@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_parent_mode_granularity_label_states_similarity_comparison(mock_bg):
    """粒度控件文案说明它是相似度比较粒度，而非输出分组粒度。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)
    dlg.combo_type.setCurrentIndex(dlg.combo_type.findData("similarity"))

    suffix = dlg.spin_granularity.suffix()
    # 标签（suffix）须说明是相似度比较粒度
    assert "相似度" in suffix
    assert "比较" in suffix
    # 不得暗示按输出分组
    assert "分组" not in suffix
    # tooltip 同样说明用于相似度比较
    assert "相似度" in dlg.spin_granularity.toolTip()


@patch("modules.rss_aggregator.dialogs.f._bind_geometry")
def test_on_granularity_changed_still_writes_config(mock_bg):
    """_on_granularity_changed 仍写回 rss.similarity_granularity（写路径不变）。"""
    store = _StubStore()
    owner = MagicMock()
    owner.store = store
    owner.context.config = _FakeConfig()
    _make_parent(store)

    from modules.rss_aggregator.dialogs.f import _AddAggregationDialog
    dlg = _AddAggregationDialog(owner, MagicMock(), parent_id=1)

    dlg._on_granularity_changed(7)

    assert owner.context.config.data["rss.similarity_granularity"] == 7
