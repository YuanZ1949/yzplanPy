"""home_tab.tab_layout2: HomeTab 布局重排与拖拽换位（_relayout_all/_finish_swap 等）。"""
from core.qt_bootstrap import import_qt
from .constants import _DEF_H, _DEF_W, _MIN_H, _MIN_W
from .tab_layout import HomeTab
_, QtCore, QtGui, QtWidgets = import_qt()
class HomeTab(HomeTab):

    def _relayout_all(self):
        """重新计算流式布局（窗口 resize 或尺寸变更时调用）。"""
        vw = max(400, self.view.viewport().width() - 20)

        items = []
        for cid in self._order:
            saved = self._saved.get(cid, {})
            w = saved.get("width", _DEF_W)
            proxy = self._proxies.get(cid)
            h = saved.get("height", proxy.size().height() if proxy else _DEF_H)
            h = max(_MIN_H, int(h))
            items.append((cid, w, h))

        positions, total_h = self._flow.compute(items, vw)

        for cid, (x, y, w, h) in positions.items():
            if cid in self._proxies:
                proxy = self._proxies[cid]
                proxy.widget().setFixedSize(w, h)
                self._update_handles(proxy, proxy.widget())
                end_pos = QtCore.QPointF(x, y)
                if proxy.pos() != end_pos:
                    if cid == self._dragging_cid:
                        # 正在拖拽的卡片不要用动画抢位置，直接落地，避免动画与拖拽互相打架
                        proxy.setPos(end_pos)
                    else:
                        self._stop_animation(cid)
                        anim = QtCore.QPropertyAnimation(proxy, b"pos")
                        anim.setDuration(250)
                        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
                        anim.setStartValue(proxy.pos())
                        anim.setEndValue(end_pos)
                        self._animations[cid] = anim
                        anim.finished.connect(lambda a=anim: self._animations.pop(cid, None) if self._animations.get(cid) is a else None)
                        anim.start()
                else:
                    self._stop_animation(cid)
                    proxy.setPos(x, y)

        self.view._sync_scene()

    def _rebuild_component(self, cid, new_w, new_h):
        old_proxy = self._proxies.get(cid)
        if old_proxy is None:
            return
        self._stop_animation(cid)
        self.scene.removeItem(old_proxy)
        del self._proxies[cid]
        self._handles.pop(cid, None)
        saved = self._saved.get(cid, {})
        saved["width"] = max(_MIN_W, int(new_w))
        saved["height"] = max(_MIN_H, int(new_h))
        self._create_card(cid)
        self._relayout_all()

    def _cid_of(self, proxy):
        return next((c for c, p in self._proxies.items() if p is proxy), None)

    def _highlight_swap(self, dragging_proxy):
        drag_cid = next((c for c, p in self._proxies.items() if p is dragging_proxy), None)
        if drag_cid is None:
            return
        target_cid = self._find_swap_target(dragging_proxy, drag_cid)
        if self._swap_line is None and target_cid:
            self._swap_line = self.scene.addRect(
                0, 0, 0, 0,
                QtGui.QPen(QtGui.QColor(0, 120, 215, 180), 2, QtCore.Qt.DashLine),
                QtGui.QBrush(QtCore.Qt.NoBrush),
            )
            self._swap_line.setZValue(50)
        if target_cid and target_cid in self._proxies:
            tp = self._proxies[target_cid]
            r = tp.widget().rect()
            self._swap_line.setRect(tp.pos().x(), tp.pos().y(), r.width(), r.height())
            self._swap_line.setVisible(True)
        elif self._swap_line:
            self._swap_line.setVisible(False)

    def _find_swap_target(self, dragging_proxy, drag_cid):
        center = dragging_proxy.pos() + QtCore.QPointF(
            dragging_proxy.widget().width() / 2,
            dragging_proxy.widget().height() / 2,
        )
        best_cid = None
        best_dist = float("inf")
        for cid, proxy in self._proxies.items():
            if cid == drag_cid:
                continue
            r = proxy.widget().rect()
            pc = proxy.pos() + QtCore.QPointF(r.width() / 2, r.height() / 2)
            dist = (center - pc).manhattanLength()
            if dist < best_dist and dist < max(r.width(), r.height()):
                best_dist = dist
                best_cid = cid
        return best_cid

    def _finish_swap(self, dragging_proxy):
        if self._swap_line:
            self._swap_line.setVisible(False)
            self.scene.removeItem(self._swap_line)
            self._swap_line = None
        drag_cid = next((c for c, p in self._proxies.items() if p is dragging_proxy), None)
        if drag_cid is None:
            return
        target_cid = self._find_swap_target(dragging_proxy, drag_cid)
        if target_cid and target_cid in self._proxies:
            di = self._order.index(drag_cid)
            ti = self._order.index(target_cid)
            self._order[di], self._order[ti] = self._order[ti], self._order[di]
            self._schedule_save()
            self._save_order()
