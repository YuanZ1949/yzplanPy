"""窗口几何信息持久化：把各类窗口/对话框的大小与位置存入全局 app.db 的 ui_state 表，
启动时自动恢复，实现跨会话记忆。"""

import contextlib
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

    @contextlib.contextmanager
    def _conn(self):
        """每次调用创建独立连接，退出 with 块时必定关闭。

        为什么必须显式 close()：`with sqlite3.Connection` 只提交/回滚，
        **不会关闭**连接。而 main.py 调用 `gc.disable()`（防止后台线程回收
        shiboken/Qt 包装对象导致 access violation），sqlite3.Connection 与其
        语句缓存又构成引用环，引用计数无法回收 —— 不显式关闭的连接会永久驻留，
        每次窗口几何读写（apply/capture）都泄漏一个。

        改为 contextmanager 后调用方写法 `with self._conn() as conn:` 保持不变。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:  # 正常结束提交，异常回滚
                yield conn
        finally:
            conn.close()

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

    def apply(self, widget, key, default_size=None, enforce_min=True, min_fit_ratio=0.0,
              center_if_missing=False):
        """恢复窗口几何。default_size=(w,h) 用于无记录时的初始尺寸。返回是否有记录。

        min_fit_ratio>0 时：若保存的宽或高相对所在屏幕的可视范围小于该比例（且未最大化），
        视为"偏小"不恢复，返回 False，交给调用方执行自适应默认尺寸。

        center_if_missing=True 时：无记录（或保存位置在屏幕外）且给了 default_size，
        resize 后把窗口中心对齐到所在屏幕 availableGeometry().center()（首次打开居中）。
        默认 False 保持旧行为，主窗口等既有调用方不受影响。
        """
        state = self.store.load(key)
        if not state:
            if default_size:
                widget.resize(default_size[0], default_size[1])
                if center_if_missing:
                    self._center_on_screen(widget)
            return False
        try:
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QGuiApplication

            w, h = state["w"], state["h"]
            if min_fit_ratio and not state.get("maximized"):
                avail = self._available_geometry(widget, w, h)
                if avail is not None and (
                    w < avail.width() * min_fit_ratio or h < avail.height() * min_fit_ratio
                ):
                    return False
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
                elif center_if_missing:
                    self._center_on_screen(widget)
            if state.get("maximized"):
                widget.showMaximized()
        except Exception as exc:
            if self._logger:
                self._logger.debug("窗口几何恢复失败 key=%s: %s", key, exc)
            return False
        return True

    @staticmethod
    def _available_geometry(widget, w, h):
        """返回目标位置所在屏幕的可视范围（QRect），获取失败返回 None。"""
        try:
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QGuiApplication

            pos = widget.pos()
            if pos.isNull():
                pos = QPoint(w, h)
            screen = QGuiApplication.screenAt(QPoint(pos.x() + w // 2, pos.y() + h // 2))
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return None
            return screen.availableGeometry()
        except Exception:
            return None

    @staticmethod
    def _center_on_screen(widget):
        """把窗口中心对齐到所在屏幕可视范围中心（无记录首次打开时居中）。

        窗口尚未 show（apply 在 __init__ 中调用），用光标所在屏幕作为"所在屏幕"
        的代理（与 open_module_page 计算默认尺寸的取屏逻辑一致），取不到再回退
        主屏。静默失败：居中只是体验优化，失败不应影响窗口打开。
        """
        try:
            from PySide6.QtGui import QGuiApplication, QCursor

            screen = QGuiApplication.screenAt(QCursor.pos())
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
            geo = widget.frameGeometry()
            geo.moveCenter(avail.center())
            widget.move(geo.topLeft())
        except Exception:
            pass

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
