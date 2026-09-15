"""RSS 侧栏：排序/重载/查询数据。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .sidebar import _RssSidebar, _SidebarNode
from .text_utils import _qf, _relative_time, rss_palette
from .utils import _decode_feed_icon
from core.theme.tokens import sizing
from .sidebar_rows import _build_rows

# favicon 解码缓存：feed_id → (icon_base64, QIcon)。
# 侧栏每次 reload 都会为每个订阅源把 base64 解码成 QIcon，订阅量大时重复解码是重载卡顿的贡献因素。
# 命中条件：同一 feed 的 icon 数据未变化（value 中比对 base64 原文），变化即失效重新解码。
# 上限 _ICON_CACHE_MAX，超限整体清空重建（简单有界，避免长期运行内存膨胀）。
_ICON_CACHE_MAX = 512
_ICON_CACHE = {}


def _cached_feed_icon(feed_id, icon_data):
    """返回 feed 的 QIcon；icon 数据未变时命中缓存，避免重复 base64 解码。

    icon 为空/未设置时返回 None（调用方走 GLOBE 回退），不缓存；
    无法解码或解码结果为 null 时同样返回 None 且不缓存。
    """
    icon_data = icon_data or ""
    if not icon_data:
        return None
    hit = _ICON_CACHE.get(feed_id)
    if hit is not None and hit[0] == icon_data:
        return hit[1]
    icon = _decode_feed_icon(icon_data)
    if icon is None or icon.isNull():
        return None
    if len(_ICON_CACHE) >= _ICON_CACHE_MAX:
        _ICON_CACHE.clear()
    _ICON_CACHE[feed_id] = (icon_data, icon)
    return icon


class _RssSidebar(_RssSidebar):  # type: ignore[reportGeneralTypeIssues]

    # ── 数据加载与排序 ─────────────────────────────────────
    def _sort_nodes(self, nodes):
        field = self._sort_field
        desc = self._sort_desc

        def key(n):
            if field == "name":
                v = (n.get("name") or "").lower()
            elif field == "added":
                v = n.get("created_at") or ""
            else:  # updated（feeds.last_refresh / aggregations.last_refreshed）
                v = n.get("last_refresh") or n.get("last_refreshed") or ""
                return (v == "", v)
            return v

        return sorted(nodes, key=key, reverse=desc)

    def _apply_sort(self, index):
        cfg = self.owner.context.config
        if 0 <= index < len(self.SORT_OPTIONS):
            label, field, desc = self.SORT_OPTIONS[index]
            self._sort_field, self._sort_desc = field, desc
            cfg.set("rss.sidebar.sort", index)

    def reload(self, reselect=False):
        prev = self.current_data()
        self._apply_sort(self.combo_sort.currentIndex())
        self.list.blockSignals(True)
        self.list.clear()
        self._nodes = []
        data = self.owner.store.list_sidebar()
        cfg = self.owner.context.config

        def feed_icon(feed):
            icon = _cached_feed_icon(feed.get("id"), feed.get("icon") or "")
            if not icon or icon.isNull():
                return _qf()["FluentIcon"].GLOBE.icon()
            return icon

        rows = _build_rows(self, data, feed_icon)

        # 恢复选中
        def _match(item):
            d = item.data(QtCore.Qt.UserRole)
            if not d or not prev:
                return False
            if d.get("kind") == prev.get("kind"):
                if d.get("kind") == "feed" and d.get("feed_id") == prev.get("feed_id"):
                    return True
                if d.get("kind") == "agg" and d.get("agg_id") == prev.get("agg_id"):
                    return True
                if d.get("kind") == "all":
                    return True
            return False

        restored = False
        if prev:
            for i in range(self.list.count()):
                if _match(self.list.item(i)):
                    self.list.setCurrentRow(i)
                    restored = True
                    break
        if restored:
            self.list.blockSignals(False)
            self.page.on_sidebar_selection_changed()
            return
        if not restored and reselect:
            snap = cfg.get("rss.sidebar.kind")
            if snap == "agg":
                aid = cfg.get("rss.sidebar.agg_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d and d.get("kind") == "agg" and d.get("agg_id") == aid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
            elif snap == "feed":
                fid = cfg.get("rss.sidebar.feed_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d and d.get("kind") == "feed" and d.get("feed_id") == fid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.page.on_sidebar_selection_changed()

    def current_data(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def current_filter(self):
        d = self.current_data()
        if not d:
            return {}
        kind = d.get("kind")
        if kind == "feed":
            return {"feed_ids": [d.get("feed_id")]}
        if kind == "agg":
            return {"agg_id": d.get("agg_id"), "agg_type": d.get("agg_type")}
        if kind == "unread":
            return {"unread_only": True}
        if kind == "fav":
            return {"favorites_only": True}
        if kind == "torrent":
            return {"type_magnet": True}
        return {}
