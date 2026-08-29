"""窗口几何信息持久化：把各类窗口/对话框的大小与位置存入全局 app.db 的 ui_state 表，
启动时自动恢复，实现跨会话记忆。"""

import os
import sqlite3

from .constants import DB_PATH

_geometry = None


def window_geometry():
    """全局共享的 WindowGeometry 单例。"""
    global _geometry
    if _geometry is None:
        import logging
        _geometry = WindowGeometry(logger=logging.getLogger("ui"))
    return _geometry


class UiStateStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_state(
                    key TEXT PRIMARY KEY,
                    w INTEGER,
                    h INTEGER,
                    x INTEGER,
                    y INTEGER,
                    maximized INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                )
                """
            )

    def load(self, key):
        with self._conn() as conn:
            row = conn.execute(
                "SELECT w, h, x, y, maximized FROM ui_state WHERE key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {
            "w": row["w"],
            "h": row["h"],
            "x": row["x"],
            "y": row["y"],
            "maximized": bool(row["maximized"]),
        }

    def save(self, key, w, h, x=None, y=None, maximized=False):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO ui_state(key, w, h, x, y, maximized, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                ON CONFLICT(key) DO UPDATE SET
                    w=excluded.w,
                    h=excluded.h,
                    x=excluded.x,
                    y=excluded.y,
                    maximized=excluded.maximized,
                    updated_at=excluded.updated_at
                """,
                (key, int(w), int(h),
                 (int(x) if x is not None else None),
                 (int(y) if y is not None else None),
                 (1 if maximized else 0)),
            )

    def remove(self, key):
        with self._conn() as conn:
            conn.execute("DELETE FROM ui_state WHERE key=?", (key,))


class WindowGeometry:
    """辅助类：把 Qt 窗口的几何读写封装成通用接口。"""

    def __init__(self, store=None, logger=None):
        self.store = store or UiStateStore()
        self._logger = logger

    def apply(self, widget, key, default_size=None, enforce_min=True):
        """恢复窗口几何。default_size=(w,h) 用于无记录时的初始尺寸。返回是否有记录。"""
        state = self.store.load(key)
        if not state:
            if default_size:
                widget.resize(default_size[0], default_size[1])
            return False
        try:
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QGuiApplication

            w, h = state["w"], state["h"]
            if enforce_min:
                w = max(w, widget.minimumWidth() or 1)
                h = max(h, widget.minimumHeight() or 1)
            widget.resize(w, h)
            x, y = state.get("x"), state.get("y")
            if x is not None and y is not None:
                # 避免恢复到屏幕之外
                screen = QGuiApplication.screenAt(QPoint(x + w // 2, y + h // 2))
                if screen is not None:
                    widget.move(x, y)
            if state.get("maximized"):
                widget.showMaximized()
        except Exception as exc:
            if self._logger:
                self._logger.debug("窗口几何恢复失败 key=%s: %s", key, exc)
            return False
        return True

    def capture(self, widget, key):
        """记录当前窗口几何。"""
        try:
            maximized = widget.isMaximized() if hasattr(widget, "isMaximized") else False
            size = widget.size()
            pos = widget.pos()
            self.store.save(
                key, size.width(), size.height(), pos.x(), pos.y(),
                maximized=maximized,
            )
        except Exception as exc:
            if self._logger:
                self._logger.debug("窗口几何保存失败 key=%s: %s", key, exc)
