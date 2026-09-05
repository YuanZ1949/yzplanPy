"""home_tab.tab_layout: HomeTab 卡片渲染（_render_all/_create_card 等）。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import CardWidget, StrongBodyLabel, TransparentToolButton
from .constants import _DEF_H, _DEF_W, _MIN_H, _MIN_W
from .handle import _Handle
from .proxy import _Proxy
from .tab_core import HomeTab
_, QtCore, QtGui, QtWidgets = import_qt()
class HomeTab(HomeTab):

    def _render_all(self):
        for cid, proxy in list(self._proxies.items()):
            self._stop_animation(cid)
            self.scene.removeItem(proxy)
        self._proxies.clear()
        self._handles.clear()

        for cid in self._order:
            self._create_card(cid)

        self._relayout_all()
        self._save_order()

    def _create_card(self, cid):
        """创建组件卡片并加入场景，但不设置位置（由 _relayout_all 统一设）。"""
        mod = self.context.registry.get(cid)
        if mod is None:
            return

        saved = self._saved.get(cid, {})
        card_w = saved.get("width", _DEF_W)

        card = CardWidget()
        card.setObjectName(f"home_card_{cid}")
        card.setMinimumWidth(_MIN_W)
        card.resize(card_w, saved.get("height", _DEF_H))

        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(10, 4, 10, 6)
        head = QtWidgets.QHBoxLayout()
        title = StrongBodyLabel(mod.name)

        close = TransparentToolButton("\u2715")
        close.setToolTip("移除")
        close.clicked.connect(lambda c=cid: self._remove_component(c))
        close.setVisible(False)

        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        lay.addLayout(head)

        card._action_btns = [close]

        def _enter(_event):
            for b in card._action_btns:
                b.setVisible(True)

        def _leave(_event):
            for b in card._action_btns:
                b.setVisible(False)

        card.enterEvent = _enter
        card.leaveEvent = _leave

        inner = mod.create_home_widget(card)
        if inner is not None:
            lay.addWidget(inner, 1)
            if hasattr(inner, "render"):
                try:
                    inner.render()
                except Exception:
                    pass

        proxy = _Proxy(self)
        proxy.setWidget(card)
        self.scene.addItem(proxy)
        self._proxies[cid] = proxy

        handles = {}
        for mode in ("r", "b", "c"):
            handle = _Handle(self, proxy, card, mode, cid)
            handle.setParentItem(proxy)
            handles[mode] = handle
        self._handles[cid] = handles
        self._update_handles(proxy, card)

    def _update_handles(self, proxy, card):
        cid = next((c for c, p in self._proxies.items() if p is proxy), None)
        if cid is None or cid not in self._handles:
            return
        w, h = card.width(), card.height()
        hs = self._handles[cid]
        hs["r"].setPos(w, h // 2)
        hs["b"].setPos(w // 2, h)
        hs["c"].setPos(w, h)

    def _stop_animation(self, cid):
        anim = self._animations.pop(cid, None)
        if anim is not None:
            try:
                anim.stop()
            except RuntimeError:
                pass
            anim.setTargetObject(None)
