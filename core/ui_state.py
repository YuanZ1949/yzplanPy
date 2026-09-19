"""窗口几何信息持久化：把各类窗口/对话框的大小与位置存入全局 app.db 的 ui_state 表，
启动时自动恢复，实现跨会话记忆。"""

import contextlib
import os
import sqlite3

from .constants import DB_PATH

# 窗口恢复时判定"在屏幕外"的可见比例阈值：完整窗口矩形在所有屏幕
# 可视范围内的可见面积占比低于该值即视为屏外，触发重新居中。
MIN_VISIBLE_RATIO = 0.5

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
                    # 默认窗口可能宽于所在屏幕（首次打开的尺寸按大屏计算），
                    # 居中后左上角会落在屏外，同样钳回可视范围。
                    self._clamp_to_screen(widget)
            return False
        try:
            from PySide6.QtCore import QRect

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
                # 避免恢复到屏幕之外：检查完整窗口矩形在所有屏幕可视范围内的
                # 可见比例，而非仅中心点（中心在屏内但左上角在屏外的记录
                # 此前会被原样恢复到屏幕之外）。
                target = QRect(x, y, w, h)
                if self._visible_ratio(target) >= MIN_VISIBLE_RATIO:
                    widget.move(x, y)
                    self._clamp_to_screen(widget)
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
        """返回与窗口矩形交集最大的屏幕的可视范围（QRect），获取失败返回 None。"""
        try:
            from PySide6.QtCore import QPoint, QRect
            from PySide6.QtGui import QGuiApplication

            pos = widget.pos()
            if pos.isNull():
                pos = QPoint(w, h)
            rect = QRect(pos.x(), pos.y(), w, h)
            best = None
            best_area = 0
            for screen in QGuiApplication.screens():
                avail = screen.availableGeometry()
                inter = rect.intersected(avail)
                area = max(0, inter.width()) * max(0, inter.height())
                if area > best_area:
                    best_area = area
                    best = avail
            if best is None:
                screen = QGuiApplication.primaryScreen()
                if screen is None:
                    return None
                best = screen.availableGeometry()
            return best
        except Exception:
            return None

    @staticmethod
    def _visible_ratio(rect):
        """返回 rect 在所有屏幕可视范围内的可见面积比例（0.0~1.0）。"""
        from PySide6.QtGui import QGuiApplication

        total = 0
        for screen in QGuiApplication.screens():
            inter = rect.intersected(screen.availableGeometry())
            if inter.width() > 0 and inter.height() > 0:
                total += inter.width() * inter.height()
        area = rect.width() * rect.height()
        if area <= 0:
            return 0.0
        return total / area

    @staticmethod
    def _clamp_to_screen(widget):
        """把窗口左上角拉回所在屏幕可视范围（恢复后调用，幂等）。

        仅当完整窗口矩形与屏幕可视区的交集面积比例 >= MIN_VISIBLE_RATIO 时
        apply 才会原样 move —— 此时左上角仍可能在屏外（如把窗口拖到双屏边缘
        后保存：可见比例 ≥0.5 但左上角挂屏幕外），不钳制就出现「窗口启动后
        左上角超出屏幕」无法拖动的问题。钳制规则：左/上越界 → 拉回边界；窗口
        窄于所在屏幕时右/下缘溢出 → 整体收进可视区；窗口宽于屏幕时保持原位置
        （右/下溢出不可避免且可接受），仅保证左/上角可见。
        """
        try:
            from PySide6.QtCore import QRect

            geo = widget.frameGeometry()
            avail = WindowGeometry._available_geometry(widget, geo.width(), geo.height())
            if avail is None:
                return
            right_edge = avail.right() + 1
            bottom_edge = avail.bottom() + 1
            x = geo.x()
            if x < avail.left():
                x = avail.left()
            elif geo.width() <= avail.width() and x + geo.width() > right_edge:
                x = right_edge - geo.width()
            y = geo.y()
            if y < avail.top():
                y = avail.top()
            elif geo.height() <= avail.height() and y + geo.height() > bottom_edge:
                y = bottom_edge - geo.height()
            if (x, y) != (geo.x(), geo.y()):
                widget.move(x, y)
        except Exception:
            pass

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
