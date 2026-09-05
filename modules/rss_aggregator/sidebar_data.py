"""RSS 侧栏：排序/重载/查询数据。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .sidebar import _RssSidebar
from .text_utils import _qf, _rss_colors
from .utils import _decode_feed_icon

class _RssSidebar(_RssSidebar):

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
            icon = _decode_feed_icon(feed.get("icon") or "")
            if not icon or icon.isNull():
                return _qf()["FluentIcon"].GLOBE.icon()
            return icon

        rows = []  # (label, data, icon)

        _fic = _qf()["FluentIcon"]
        node_all = {"kind": "all", "name": "全部条目", "created_at": "", "last_refresh": ""}
        rows.append(("全部条目", node_all, _fic.HOME.icon()))

        for a in self._sort_nodes(data["aggregations"]):
            label = a["name"]
            info = "{}条".format(a.get("count") or 0)
            if a.get("unread"):
                info += "·未读{}".format(a["unread"])
            if a.get("agg_type") == "torrent":
                info += "·磁链"
            rows.append(("{} [{}]".format(label, info), {"kind": "agg", "agg_id": a["id"],
                          "agg_type": a.get("agg_type"), "name": label,
                          "created_at": a.get("created_at") or "", "last_refreshed": a.get("last_refreshed") or ""},
                         _fic.FOLDER.icon()))

        for f in self._sort_nodes([x for x in data["feeds"] if x.get("enabled")]):
            label = f["name"]
            if f.get("unread"):
                label += " ({})".format(f["unread"])
            rows.append((label, {"kind": "feed", "feed_id": f["id"], "name": f["name"],
                        "created_at": f.get("created_at") or "", "last_refresh": f.get("last_refresh") or ""},
                         feed_icon(f)))

        for label, d, icon in rows:
            item = QtWidgets.QListWidgetItem(label)
            if icon:
                item.setIcon(icon)
            item.setData(QtCore.Qt.UserRole, d)
            self.list.addItem(item)
            self._nodes.append(item)

        # 恢复选中
        def _match(item):
            d = item.data(QtCore.Qt.UserRole)
            if prev and d.get("kind") == prev.get("kind"):
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
                    if d.get("kind") == "agg" and d.get("agg_id") == aid:
                        self.list.setCurrentRow(i)
                        self.list.blockSignals(False)
                        self.page.on_sidebar_selection_changed()
                        return
            elif snap == "feed":
                fid = cfg.get("rss.sidebar.feed_id")
                for i in range(self.list.count()):
                    d = self.list.item(i).data(QtCore.Qt.UserRole)
                    if d.get("kind") == "feed" and d.get("feed_id") == fid:
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
        return {}
