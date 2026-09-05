"""RSS 工具：几何记忆、图标解码、图标加载工作线程。"""

import base64
import logging

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")

def _bind_geometry(dialog, key, default_size=None):
    """为对话框绑定几何记忆：启动恢复、关闭保存。"""
    from core.ui_state import window_geometry
    geometry = window_geometry()
    geometry.apply(dialog, key, default_size=default_size)
    dialog.finished.connect(lambda *_: geometry.capture(dialog, key))


def _decode_feed_icon(icon_data):
    """把 feeds.icon 的 base64 串转成 QIcon；无法解码返回 None。"""
    import base64
    if not icon_data:
        return None
    if icon_data.startswith("base64:"):
        icon_data = icon_data[len("base64:"):]
    try:
        raw = base64.b64decode(icon_data)
    except Exception:
        return None
    pixmap = QtGui.QPixmap()
    if pixmap.loadFromData(raw):
        return QtGui.QIcon(pixmap)
    return None


class _FaviconWorker(QtCore.QObject):
    """后台抓取订阅源 favicon 并写入 feeds.icon 缓存。"""
    done = QtCore.Signal()

    def __init__(self, store, proxy=""):
        super().__init__()
        self.store = store
        self.proxy = proxy

    def run(self):
        import base64, requests
        from urllib.parse import urlparse
        feeds = self.store.feeds_needing_favicon()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YZplan/1.0"}
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        for f in feeds:
            url = f.get("url") or ""
            host = urlparse(url).netloc or "" if url else ""
            icon = ""
            candidates = [f"https://{host}/favicon.ico", f"https://www.google.com/s2/favicons?domain={host}"]
            for c in candidates:
                if not host and "google" not in c:
                    continue
                try:
                    r = requests.get(c, timeout=8, headers=headers, proxies=proxies, verify=False)
                    if r.status_code == 200 and r.content:
                        icon = "base64:" + base64.b64encode(r.content).decode()
                        break
                except Exception:
                    continue
            self.store.set_feed_icon(f["id"], icon)
        self.done.emit()
