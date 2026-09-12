"""聚合刷新后台服务：把聚合快照重建 SQL 移入 daemon worker 线程。

与 fetchers.py 同款约定：store 实例跨线程共享（RssStore._conn() 按线程
开新连接），信号从 worker 线程 emit，Qt 自动排队到接收者线程（主线程）。
"""

import json
import logging
import threading

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")


def _refresh_for_feed_sync(store, feed_id):
    """刷新包含该订阅源的所有手动聚合及其子聚合的快照（纯 SQL，无网络）。"""
    all_aggs = store.list_aggregations()
    # 1) 直接包含该 feed 的聚合
    affected = [a["id"] for a in all_aggs
                if feed_id in json.loads(a.get("feed_ids") or "[]")]
    # 2) 父聚合被刷新 → 子聚合也需刷新
    affected += [a["id"] for a in all_aggs
                 if int(a.get("parent_id") or 0) in affected]
    affected = list(dict.fromkeys(affected))
    id_map = {a["id"]: a for a in all_aggs}
    for agg_id in affected:
        a = id_map.get(agg_id)
        if a is None:
            continue
        try:
            store.refresh_aggregation(agg_id)
            if (a.get("agg_type") or "mixed") == "similarity":
                try:
                    from .auto_exclude import sync_auto_exclude_child
                    sync_auto_exclude_child(store, agg_id)
                except Exception as ex2:
                    logger.debug("同步相似性剩余子聚合失败: %s", ex2)
        except Exception as ex:
            logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)


class AggregationService(QtCore.QObject):
    """在后台线程执行聚合刷新，完成后通过 done 信号通知主线程。"""

    done = QtCore.Signal(object)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._busy = False
        self._lock = threading.Lock()
        self._thread = None

    # ── 入口（fire-and-forget，立即返回）──────────────────────

    def refresh_for_feed(self, feed_id):
        """刷新包含该订阅源的所有手动聚合及其子聚合的快照（纯 SQL，无网络）。"""
        return self._submit(self._refresh_for_feed, feed_id)

    def refresh_one(self, agg_id):
        """刷新单个聚合快照（含相似性剩余子聚合联动）。"""
        return self._submit(self._refresh_one, agg_id)

    def refresh_all(self):
        """刷新全部聚合快照。"""
        return self._submit(self._refresh_all)

    # ── 后台批次执行 ─────────────────────────────────────────

    def _submit(self, batch_fn, *args):
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self._thread = threading.Thread(
            target=self._run_batch, args=(batch_fn, *args), daemon=True)
        self._thread.start()
        return True

    def _run_batch(self, batch_fn, *args):
        try:
            batch_fn(*args)
        except Exception as ex:
            logger.warning("聚合刷新后台任务异常: %r", ex)
        finally:
            self.done.emit({})
            with self._lock:
                self._busy = False

    def _refresh_for_feed(self, feed_id):
        _refresh_for_feed_sync(self.store, feed_id)

    def _refresh_one(self, agg_id):
        self.store.refresh_aggregation(agg_id)
        try:
            from .auto_exclude import sync_auto_exclude_child
            sync_auto_exclude_child(self.store, agg_id)
        except Exception as ex:
            logger.debug("同步相似性剩余子聚合失败: %s", ex)

    def _refresh_all(self):
        for a in self.store.list_aggregations():
            try:
                self.store.refresh_aggregation(a["id"])
            except Exception as ex:
                logger.warning("刷新聚合 %s 失败: %s", a.get("name"), ex)