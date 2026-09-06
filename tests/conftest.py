import gc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt

_, QtCore, _, QtWidgets = import_qt()

import pytest


@pytest.fixture(autouse=True)
def _qt_test_cleanup():
    gc.collect()
    gc.disable()
    app = QtWidgets.QApplication.instance()
    yield
    if app is not None:
        for w in list(QtWidgets.QApplication.topLevelWidgets()):
            try:
                if getattr(w, "isVisible", lambda: False)():
                    w.hide()
                w.close()
                w.deleteLater()
            except Exception:
                pass
        try:
            import modules.rss_aggregator as rss_aggregator
            keep = getattr(rss_aggregator, "_PREVIEW_KEEP", {})
            view = keep.get("view")
            profile = keep.get("profile")
            if view is not None:
                try:
                    view.deleteLater()
                except Exception:
                    pass
            if profile is not None:
                try:
                    profile.deleteLater()
                except Exception:
                    pass
            keep["view"] = None
            keep["page"] = None
            keep["profile"] = None
            keep["render_process_alive"] = True
        except Exception:
            pass
        app.processEvents()
        app.closeAllWindows()
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, 0)
    gc.collect()
    gc.enable()