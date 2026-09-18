"""RSS 刷新间隔：默认值 6h、humanize、拆分、钳制、迁移、dialog 控件冒烟。

纯数据层测试，不依赖 Qt（dialog 冒烟除外，离屏跑）。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---------------------------------------------------------------------------
# A) 纯函数：humanize_interval / split_interval / interval_to_seconds
# ---------------------------------------------------------------------------

class TestHumanizeInterval:
    """humanize_interval(seconds) → "6 小时" 等可读文本。"""

    def test_21600_is_6_hours(self):
        from modules.rss_store.store_feeds import humanize_interval
        assert humanize_interval(21600) == "6 小时"

    def test_1800_is_30_minutes(self):
        from modules.rss_store.store_feeds import humanize_interval
        assert humanize_interval(1800) == "30 分钟"

    def test_90_is_90_seconds(self):
        from modules.rss_store.store_feeds import humanize_interval
        assert humanize_interval(90) == "90 秒"

    def test_86400_is_1_day(self):
        from modules.rss_store.store_feeds import humanize_interval
        assert humanize_interval(86400) == "1 天"

    def test_0_is_0_seconds(self):
        from modules.rss_store.store_feeds import humanize_interval
        assert humanize_interval(0) == "0 秒"


class TestSplitInterval:
    """split_interval(seconds) → (value, unit_label)。"""

    def test_21600(self):
        from modules.rss_store.store_feeds import split_interval
        assert split_interval(21600) == (6, "小时")

    def test_1800(self):
        from modules.rss_store.store_feeds import split_interval
        assert split_interval(1800) == (30, "分钟")

    def test_90(self):
        from modules.rss_store.store_feeds import split_interval
        assert split_interval(90) == (90, "秒")

    def test_86400(self):
        from modules.rss_store.store_feeds import split_interval
        assert split_interval(86400) == (1, "天")

    def test_0(self):
        from modules.rss_store.store_feeds import split_interval
        assert split_interval(0) == (0, "秒")


class TestIntervalToSeconds:
    """interval_to_seconds(value, unit_label) → int seconds。"""

    def test_6_hours(self):
        from modules.rss_store.store_feeds import interval_to_seconds
        assert interval_to_seconds(6, "小时") == 21600

    def test_30_minutes(self):
        from modules.rss_store.store_feeds import interval_to_seconds
        assert interval_to_seconds(30, "分钟") == 1800

    def test_90_seconds(self):
        from modules.rss_store.store_feeds import interval_to_seconds
        assert interval_to_seconds(90, "秒") == 90

    def test_1_day(self):
        from modules.rss_store.store_feeds import interval_to_seconds
        assert interval_to_seconds(1, "天") == 86400


# ---------------------------------------------------------------------------
# B) 默认刷新间隔：新增源应为 21600
# ---------------------------------------------------------------------------

class TestDefaultRefreshInterval:
    """add_feed 未显式指定 refresh_interval 时应为 21600。"""

    def test_default_is_21600(self):
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("源A", "https://a.example/rss", tag="tA")
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 21600

    def test_explicit_1800_still_works(self):
        """显式传 1800 应原样存储（>= 300 不钳制）。"""
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("源B", "https://b.example/rss", tag="tB",
                              refresh_interval=1800)
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 1800


# ---------------------------------------------------------------------------
# C) 钳制：< 300 → 300
# ---------------------------------------------------------------------------

class TestRefreshIntervalClamp:
    """刷新间隔低于 min_refresh_interval 时应被钳制。"""

    def test_clamp_to_300(self):
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("小间隔", "https://c.example/rss", tag="t",
                              refresh_interval=60)
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 300

    def test_negative_clamped(self):
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("负数", "https://d.example/rss", tag="t",
                              refresh_interval=-100)
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 300

    def test_zero_clamped(self):
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("零", "https://e.example/rss", tag="t",
                              refresh_interval=0)
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 300

    def test_update_clamp(self):
        from modules.rss_store import RssStore
        store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
        fid = store.add_feed("源", "https://f.example/rss", tag="t")
        store.update_feed(fid, refresh_interval=100)
        feed = store.get_feed_by_id(fid)
        assert feed["refresh_interval"] == 300


# ---------------------------------------------------------------------------
# D) 迁移：旧库 refresh_interval=1800 → 21600
# ---------------------------------------------------------------------------

class TestMigrationDefaultRefreshInterval:
    """schema 升级应把 refresh_interval=1800 的源迁移到 21600。"""

    @staticmethod
    def _make_old_db():
        """造一个 user_version=4 的库（模拟旧版），插入 1800/3600 两条源。"""
        from modules.rss_store.store_schema_sql import _SCHEMA_SQL
        db_path = os.path.join(tempfile.mkdtemp(), "old.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.executescript(_SCHEMA_SQL)
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        # 插入两条 feeds：一条 1800（应迁移），一条 3600（不动）
        cur = conn.execute(
            "INSERT INTO feeds(name,url,tag,group_name,enabled,refresh_interval) "
            "VALUES(?,?,?,?,?,?)",
            ("旧源", "https://old.example", "tag1", "", 1, 1800),
        )
        feed_old = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO feeds(name,url,tag,group_name,enabled,refresh_interval) "
            "VALUES(?,?,?,?,?,?)",
            ("自定义", "https://custom.example", "tag2", "", 1, 3600),
        )
        feed_custom = cur2.lastrowid
        conn.commit()
        conn.close()
        return db_path, feed_old, feed_custom

    def test_migrates_1800_to_21600(self):
        from modules.rss_store import RssStore
        db_path, feed_old, feed_custom = self._make_old_db()
        store = RssStore(db_path)
        feeds = {f["id"]: f for f in store.list_feeds()}
        assert feeds[feed_old]["refresh_interval"] == 21600, \
            "1800 应迁移到 21600"
        assert feeds[feed_custom]["refresh_interval"] == 3600, \
            "非 1800 不应被改动"

    def test_idempotent(self):
        from modules.rss_store import RssStore
        db_path, feed_old, feed_custom = self._make_old_db()
        store1 = RssStore(db_path)
        _ = store1.list_feeds()  # 触发迁移
        # 再开一个实例 — 应走 fast-path，不再迁移
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA user_version = 4")  # 回退 version 模拟重复
        conn.commit(); conn.close()
        store2 = RssStore(db_path)
        feeds = {f["id"]: f for f in store2.list_feeds()}
        # 再次迁移也应正确（幂等）
        assert feeds[feed_old]["refresh_interval"] == 21600
        assert feeds[feed_custom]["refresh_interval"] == 3600

    @staticmethod
    def _make_v5_db():
        """造一个 user_version=5 的库（模拟已升级但漏迁移的库），插入 1800 源。

        真实缺口：T8 代码先跑过一遍把 user_version 升到 5（全表已建），但
        迁移函数当时未执行/未存在，导致 v5 库仍残留 refresh_interval=1800。
        先走完整 slow path 建全表并升 v5，再手动插入 1800 源模拟漏迁移行。
        """
        from modules.rss_store import RssStore
        db_path = os.path.join(tempfile.mkdtemp(), "v5.db")
        RssStore(db_path)  # 完整 slow path：建全表 + user_version=5
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "INSERT INTO feeds(name,url,tag,group_name,enabled,refresh_interval) "
            "VALUES(?,?,?,?,?,?)",
            ("漏迁移源", "https://gap.example", "tag1", "", 1, 1800),
        )
        feed_id = cur.lastrowid
        conn.commit()
        conn.close()
        return db_path, feed_id

    def test_migrates_1800_to_21600_when_already_v5(self):
        """真实缺口：库已到 user_version=5 但 feeds 仍为 1800 → 打开后应迁移。"""
        from modules.rss_store import RssStore
        db_path, feed_id = self._make_v5_db()
        store = RssStore(db_path)
        feeds = {f["id"]: f for f in store.list_feeds()}
        assert feeds[feed_id]["refresh_interval"] == 21600, \
            "v5 库中残留的 1800 也应迁移到 21600"


# ---------------------------------------------------------------------------
# E) 对话框构造冒烟：新增 combo_interval_unit 控件存在
# ---------------------------------------------------------------------------

class TestDialogIntervalWidget:
    """对话框应包含 combo_interval_unit（单位下拉）和 in_interval。"""

    def test_add_feed_dialog_has_unit_combo(self):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        from unittest.mock import MagicMock
        from modules.rss_aggregator.dialogs.b import _AddFeedDialog
        dlg = _AddFeedDialog(MagicMock())
        try:
            assert hasattr(dlg, "combo_interval_unit"), \
                "_AddFeedDialog 应有 combo_interval_unit"
            assert hasattr(dlg, "in_interval"), \
                "_AddFeedDialog 应有 in_interval"
            assert dlg.combo_interval_unit.count() == 4, \
                "单位下拉应有 4 项：秒/分钟/小时/天"
            assert dlg.combo_interval_unit.currentIndex() == 2, \
                "默认应选中 index=2（小时）"
            assert dlg.in_interval.value() == 6, \
                "默认数值应为 6"
        finally:
            dlg.hide()

    def test_edit_feed_dialog_has_unit_combo(self):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        from unittest.mock import MagicMock
        from modules.rss_aggregator.dialogs.a import _EditFeedDialog
        feed = {"id": 1, "name": "t", "url": "https://example.com",
                "feed_type": "rss", "refresh_interval": 1800}
        dlg = _EditFeedDialog(feed, MagicMock())
        try:
            assert hasattr(dlg, "combo_interval_unit"), \
                "_EditFeedDialog 应有 combo_interval_unit"
            assert hasattr(dlg, "in_interval"), \
                "_EditFeedDialog 应有 in_interval"
            # 1800 → split → (30, "分钟")
            assert dlg.combo_interval_unit.currentText() == "分钟", \
                "1800 秒应拆分为分钟"
            assert dlg.in_interval.value() == 30, \
                "1800 秒 → 数值 30"
        finally:
            dlg.hide()


# ---------------------------------------------------------------------------
# F) 回归：v5 fast-path 的迁移 UPDATE 必须提交，释放写锁
# ---------------------------------------------------------------------------

class TestFastPathReleasesWriteLock:
    """回归测试（“程序启动不了” bug）。

    v5 fast-path 里 `_migrate_default_refresh_interval` 的 UPDATE 会开启一个
    隐式写事务；若调用方不提交，连接池里的常驻连接（`RssStoreBase._conn()`
    按 (thread, db_path) 缓存、进程内不关闭）会一直持有 RESERVED 写锁。
    其它模块（如 todo 的 `INSERT OR IGNORE INTO todo_statuses`）随后拿不到
    写锁，等待 5s 超时后抛 `sqlite3.OperationalError: database is locked`，
    整个程序启动失败。

    注意：断言必须使用**独立连接**。用 `store.list_feeds()` 之类读回会命中
    同一个池化连接，从而看到未提交的数据、误判为通过 —— 这正是原测试漏检
    该 bug 的原因。
    """

    @staticmethod
    def _make_fast_path_store():
        """造 v5 库 → 二次构造走 fast-path → 返回 (db_path, store)。"""
        from modules.rss_store import RssStore
        db_path, _feed_id = TestMigrationDefaultRefreshInterval._make_v5_db()
        store = RssStore(db_path)  # user_version=5 → fast-path + 迁移 UPDATE
        return db_path, store

    def test_fast_path_leaves_no_open_transaction(self):
        _db_path, store = self._make_fast_path_store()
        assert store._conn().in_transaction is False, \
            "fast-path 迁移 UPDATE 后必须提交，否则常驻连接长期持有写锁"

    def test_separate_connection_can_acquire_write_lock_after_fast_path(self):
        import sqlite3
        db_path, _store = self._make_fast_path_store()
        other = sqlite3.connect(db_path, timeout=1)
        try:
            # BEGIN IMMEDIATE 需要 RESERVED 写锁；若 fast-path 遗留未提交的
            # 写事务，这里会抛 sqlite3.OperationalError: database is locked。
            other.execute("BEGIN IMMEDIATE")
            other.execute(
                "INSERT OR IGNORE INTO feeds"
                "(name,url,tag,group_name,enabled,refresh_interval) "
                "VALUES(?,?,?,?,?,?)",
                ("并发写入源", "https://concurrent.example", "", "", 1, 21600),
            )
            other.commit()
        finally:
            other.close()
