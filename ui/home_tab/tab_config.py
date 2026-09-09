"""home_tab.tab_config: HomeTab 组件增删与布局持久化（_add_component/_save_layout 等）。"""
from core.qt_bootstrap import import_qt
from .constants import _DEF_H, _DEF_W, _MIN_H, _MIN_W
from .picker import _AddPopup
from .tab_layout2 import HomeTab
_, QtCore, QtGui, QtWidgets = import_qt()
class HomeTab(HomeTab):  # type: ignore[reportGeneralTypeIssues]

    def _show_add_popup(self):
        popup = _AddPopup(self, self.widget)
        btn_pos = self.btn_add.mapToGlobal(QtCore.QPoint(0, self.btn_add.height()))
        popup.move(btn_pos)
        popup.show()

    def _add_component(self, cid):
        if cid not in self._order:
            self._order.append(cid)
            self._render_all()

    def _remove_component(self, cid):
        if cid in self._order:
            self._order.remove(cid)
        if cid in self._saved:
            del self._saved[cid]
        self._render_all()

    def _reset_layout(self):
        self._order = [cid for cid, _ in self._comp_index]
        self._saved = {cid: {"width": _DEF_W, "height": _DEF_H} for cid in self._order}
        self._render_all()

    def _clear_layout(self):
        self._order = []
        self._saved = {}
        self._render_all()

    def _schedule_save(self):
        self._save_pending.start(300)

    def _save_layout(self):
        layout = {}
        for cid in self._order:
            saved = self._saved.get(cid, {})
            layout[cid] = {
                "width": saved.get("width", _DEF_W),
                "height": saved.get("height", _DEF_H),
            }
        self.context.config.set("home.layout", layout)

    def _save_order(self):
        self.context.config.set("home.order", self._order)
