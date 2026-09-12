"""RSS 页面：_RssPageWidget（构造与初始化）。"""

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .text_utils import rss_palette, rss_style_vars


class _RssPageWidget(QtWidgets.QWidget):
    frameless = True  # 打开时使用无边框自定义标题栏窗口

    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self._current_page = 0
        self._all_items = []
        self._show_thumbnails = owner.context.config.get("rss.show_thumbnails", False)
        self._last_clicked_row = -1
        self._selected_hashes = set()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        self._node_item_by_head = {}
        self._group_children = {}
        self._head_buttons = {}
        self._head_by_member = {}
        # 聚合分页状态（磁链/相似性聚合按分组头分页，_agg_expanded 跨页保留展开）
        self._agg_mode = False
        self._agg_page = 0
        self._agg_groups = []
        self._agg_total_items = 0
        self._agg_kind_label = ""
        self._agg_expanded = set()
        self._title_bar_migrated = False

        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)

        rss_c = rss_style_vars()

        # ── UI 构建（从 paintEvent 移入 __init__）──────────────
        self._build_ui(rss_c)

    def _save_col_widths(self):
        """把当前三栏宽度存为比例到配置 `rss.col_widths`（供下次打开恢复）。

        存比例而非像素，窗口每次打开宽度不同也能等比还原。
        取值优先用拖拽目标宽度（_side_width 等），布局未激活时
        widget.width() 可能还是旧值。
        """
        side = self._side_width if self._side_width is not None else self._side_col.width()
        lst = self._list_width if self._list_width is not None else self._list_col.width()
        prev = self._preview_width if self._preview_width is not None else self._preview_col.width()
        total = side + lst + prev
        if total <= 0:
            return
        self.owner.context.config.set("rss.col_widths", {
            "side": round(side / total, 4),
            "list": round(lst / total, 4),
            "preview": round(prev / total, 4),
        })

    def _restore_col_widths(self):
        """从配置读取 `rss.col_widths`（三栏宽度比例）并在本页初始布局中应用。

        本方法在 `_build_ui` 结尾（三栏已加入布局、但窗口尚未布局）调用：
        此时布局几何通常为 0，按基准宽 1200 换算像素宽；窗口显示并触发
        resizeEvent 后会自动按真实可用宽度等比修正。
        """
        ratios = self.owner.context.config.get("rss.col_widths")
        if not isinstance(ratios, dict):
            return
        nums = []
        for k in ("side", "list", "preview"):
            v = ratios.get(k)
            if not isinstance(v, (int, float)) or v <= 0:
                return
            nums.append(float(v))
        avail = self._three_col.geometry().width()
        known = avail > 0
        if not known:
            avail = 1200  # 尚未布局：用基准宽度，resizeEvent 会等比修正
        total = sum(nums)
        if total <= 0:
            return
        side = max(140, int(nums[0] / total * avail))
        lst = max(160, int(nums[1] / total * avail))
        prev = max(160, int(nums[2] / total * avail))
        # 钳制仅在真实布局宽度已知时生效：基准 1200 是未布局的占位近似，
        # 交给 resizeEvent 按真实可用宽等比修正（避免误伤初始恢复的期望值）
        if known:
            side, lst, prev = self._clamp_widths(side, lst, prev, avail)
        self._side_width, self._list_width, self._preview_width = side, lst, prev
        self._apply_sizes()

    def _apply_sizes(self):
        """把 _side_width/_list_width/_preview_width 应用到三栏（像素固定宽）。"""
        if self._side_width is not None:
            self._side_col.setFixedWidth(self._side_width)
        else:
            self._side_col.setMinimumWidth(0)
            self._side_col.setMaximumWidth(16777215)
        if self._list_width is not None:
            self._list_col.setFixedWidth(self._list_width)
        else:
            self._list_col.setMinimumWidth(0)
            self._list_col.setMaximumWidth(16777215)
        if self._preview_width is not None:
            self._preview_col.setFixedWidth(self._preview_width)
        else:
            self._preview_col.setMinimumWidth(0)
            self._preview_col.setMaximumWidth(16777215)

    def _clamp_widths(self, side, lst, prev, avail):
        """把三栏总宽钳制到容器可用宽内，防止溢出挤压/覆盖拖拽手柄。

        三栏固定宽之和（含 2 个 7px 手柄 = 14px）若超过容器可用宽，
        QHBoxLayout 会从右缘裁剪预览列、极端情况下把拖拽手柄挤出可见区
        （表现为"预览扩宽挡住了手柄2"）。这里按 预览→列表→侧栏 的优先级
        收缩，各列保底 100/100/84px，保证手柄永远位于布局内且可拖拽。
        """
        grips = 14  # 2 个 7px 拖拽手柄
        if avail <= 0:
            return side, lst, prev
        budget = avail - grips
        if side + lst + prev <= budget:
            return side, lst, prev
        # 保底：极小窗口下也保留可操作的最小宽度
        min_side, min_list, min_prev = 84, 100, 100
        side = max(min_side, side)
        lst = max(min_list, lst)
        prev = max(min_prev, prev)
        over = side + lst + prev - budget
        if over > 0:
            prev = max(min_prev, prev - over)
        over = side + lst + prev - budget
        if over > 0:
            lst = max(min_list, lst - over)
        over = side + lst + prev - budget
        if over > 0:
            side = max(min_side, side - over)
        return side, lst, prev

    def resizeEvent(self, event):
        """窗口整体缩放时按比例重置三栏宽度，避免挤压到零宽。"""
        super().resizeEvent(event)
        if self._drag_active:
            return
        side, lst, prev = self._side_width, self._list_width, self._preview_width
        if side is None and lst is None and prev is None:
            return
        side = side if side is not None else 0
        lst = lst if lst is not None else 0
        prev = prev if prev is not None else 0
        total = side + lst + prev
        if total <= 0:
            return
        avail = max(0, self._three_col.geometry().width())
        if avail <= 0:
            return
        self._side_width = max(120, int(side * avail / total))
        self._list_width = max(160, int(lst * avail / total))
        self._preview_width = max(160, int(prev * avail / total))
        side, lst, prev = self._clamp_widths(
            self._side_width, self._list_width, self._preview_width, avail)
        self._side_width, self._list_width, self._preview_width = side, lst, prev
        self._apply_sizes()

    def _update_thumbnail_btn_text(self):
        if getattr(self, "_title_bar_migrated", False):
            self.btn_thumb.setText("缩略图")
        else:
            self.btn_thumb.setText("隐藏缩略图" if self._show_thumbnails else "显示缩略图")

    def _toggle_thumbnails(self, checked):
        self._show_thumbnails = checked
        self.owner.context.config.set("rss.show_thumbnails", checked)
        self._update_thumbnail_btn_text()
        self._load_items()

    def paintEvent(self, event):
        """v4 径向渐变背景——深色蓝+紫+绿，浅色蓝。"""
        c = rss_palette()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if c["dark"]:
            # 底色
            p.fillRect(self.rect(), QtGui.QColor(c["rss_page_bg"]))
            # 径向渐变：中心蓝 → 紫 → 绿 → 透明
            grad = QtGui.QRadialGradient(w / 2, h / 2, max(w, h) * 0.55)
            grad.setColorAt(0.0, QtGui.QColor(74, 163, 255, 51))   # 0.20
            grad.setColorAt(0.4, QtGui.QColor(160, 107, 255, 26))  # 0.10
            grad.setColorAt(0.7, QtGui.QColor(37, 205, 150, 15))   # 0.06
            grad.setColorAt(1.0, QtCore.Qt.transparent)
        else:
            # 底色
            p.fillRect(self.rect(), QtGui.QColor(c["rss_page_bg"]))
            # 径向渐变：上方蓝
            grad = QtGui.QRadialGradient(w / 2, h * 0.3, max(w, h) * 0.55)
            grad.setColorAt(0.0, QtGui.QColor(26, 115, 232, 38))   # 0.15
            grad.setColorAt(0.6, QtGui.QColor(26, 115, 232, 8))    # 0.03
            grad.setColorAt(1.0, QtCore.Qt.transparent)
        p.setBrush(grad)
        p.setPen(QtCore.Qt.NoPen)
        p.drawRect(self.rect())
        p.end()