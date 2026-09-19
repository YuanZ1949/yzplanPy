"""ui/adaptive_table_filter.py: 表格列宽自适应过滤器（_AdaptiveFilter）。"""
from core.qt_bootstrap import import_qt

_, QtCore, _, QtWidgets = import_qt()
# 表格单元格内容可用宽度的水平内边距（左+右）。
# PySide6/Qt 默认 item delegate 在每个单元格内留约 8px 左+8px 右的内边距，
# 列宽必须扣除此值才是文本可渲染的真实宽度。之前各模块各自硬编码 -8 过小导致
# 文字被边框遮挡；统一为 16px 并提取为共享常量。
CELL_CONTENT_PAD = 16


class _AdaptiveFilter(QtCore.QObject):
    default_header_delta = 40  # 表头文本左右留白

    def __init__(self, table_widget, min_column_width=None, width_caps=None, min_widths=None,
                 persist_key=None, config=None):
        super().__init__(table_widget)
        self.table = table_widget
        # 最小列宽必须容纳单元格内边距 + 少量文本，否则内容会被边框遮挡。
        if min_column_width is None:
            min_column_width = CELL_CONTENT_PAD + 24
        self.min_column_width = min_column_width
        # 某些折行/弹性列（如“内容”）不应把原始全文按单行测宽——那会让该列吃满窗口、
        # 挤压其余窄列导致其内容被截断/换行。width_caps: {列号: 该列最多占视口宽的比例 0~1}。
        self._width_caps = width_caps or {}
        # 某些列（如全选表头按钮列）需要保证最小宽度，等比缩放后也不得低于该值。
        # min_widths: {列号: 最小像素宽}。
        self._min_widths = min_widths or {}
        self._header = table_widget.horizontalHeader()
        self._base_widths = None       # 用户调整后的基准列宽（按列序）
        self._resizing = False         # 程序化 resize 中，避免被 sectionResized 反向记录
        self._ready = False
        self._pending = False          # 已排队待执行的延迟 reflow
        self._last_reflow_w = -1       # 上次 reflow 时的视口宽（用于过滤滚动条引起的伪 resize）
        self._persist_key = persist_key
        self._config = config
        self._save_timer = None        # 600ms 防抖后写配置

        # 允许表格随窗口收缩（否则 Interactive 内容宽度会成为最小宽度，
        # 在特定宽度处无法继续等比缩放，出现“列宽突然还原/卡住”）
        table_widget.setMinimumWidth(0)
        table_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                   QtWidgets.QSizePolicy.Expanding)
        self._header.setMinimumSectionSize(20)
        self._header.setDefaultSectionSize(80)

        self._set_all_interactive()
        # sectionResized: 用户拖拽（或任何外部改动）记录为新基准
        self._header.sectionResized.connect(self._on_section_resized)
        table_widget.installEventFilter(self)
        # viewport 也要监听：垂直滚动条出现/消失只改变 viewport 宽度而 table 尺寸不变，
        # 若不重排，右边缘会残留未填充的空隙。
        table_widget.viewport().installEventFilter(self)
        # 若配置里存过列宽，直接作为基准恢复（否则做首次自适应测量）
        if not self._load_persisted():
            QtCore.QTimer.singleShot(0, self._first_measure)

    def _set_all_interactive(self):
        for c in range(self.table.columnCount()):
            self._header.setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)

    # ── 首次测量：按表头/内容自适应初值 ──────────────────────────────
    def _first_measure(self):
        if self._ready:
            return
        if self.table.width() <= 0 or self.table.columnCount() == 0:
            QtCore.QTimer.singleShot(0, self._first_measure)
            return
        widths = []
        for c in range(self.table.columnCount()):
            w = self._content_width(c)
            widths.append(max(self.min_column_width, w))
        self._base_widths = list(widths)
        self._ready = True
        self._reflow()

    def _content_width(self, col):
        fm = self._header.fontMetrics()
        header_text = self._header.model().headerData(col, QtCore.Qt.Horizontal) or ""
        cw = fm.horizontalAdvance(header_text) + self.default_header_delta
        limit = min(50, self.table.rowCount())
        for r in range(limit):
            item = self.table.item(r, col)
            if item is not None:
                # 单元格内边距 + 8px 安全余量（字体度量可能略小于实际渲染宽度）
                cw = max(cw, fm.horizontalAdvance(item.text()) + CELL_CONTENT_PAD + 8)
        # 指定的弹性/折行列：最多占视口宽的一定比例，避免其按原始全文测宽后吃满窗口，
        # 挤压其余窄列导致内容被截断/换行。
        ratio = self._width_caps.get(col)
        if ratio:
            vw = self.table.viewport().width()
            cap = max(250.0, int(vw * ratio))
            cw = min(cw, cap)
        return cw

    # ── 记录基准列宽（用户调整后）────────────────────────────────────
    def _on_section_resized(self, logical_idx, old_size, new_size):
        # 程序化缩放期间忽略，避免把缩放结果反向记为基准
        if self._resizing:
            return
        if self._base_widths is None or logical_idx >= len(self._base_widths):
            return
        self._base_widths[logical_idx] = new_size
        self._schedule_save()

    # ── 列宽持久化（可选：persist_key+config 启用）──────────────────
    def _load_persisted(self):
        """从配置恢复上次保存的基准列宽。成功返回 True，否则走首次自适应测量。"""
        if not self._persist_key or not self._config:
            return False
        saved = self._config.get(self._persist_key)
        if not isinstance(saved, list) or not saved:
            return False
        n = self.table.columnCount()
        if n == 0:
            return False
        # 用配置值补齐/截断到当前列数；非法项回退为最小宽
        widths = []
        for i in range(n):
            v = saved[i] if i < len(saved) else None
            if isinstance(v, (int, float)) and v > 0:
                widths.append(max(self.min_column_width, int(v)))
            else:
                widths.append(self.min_column_width)
        self._base_widths = widths
        self._ready = True
        QtCore.QTimer.singleShot(0, self._reflow)
        return True

    def _schedule_save(self):
        if not self._persist_key or not self._config:
            return
        if self._save_timer is None:
            self._save_timer = QtCore.QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(600)  # 防抖：拖拽过程产生大量 sectionResized
            self._save_timer.timeout.connect(self._save)
        self._save_timer.start()

    def _save(self):
        if self._base_widths is None or not self._persist_key or not self._config:
            return
        self._config.set(self._persist_key, [int(w) for w in self._base_widths])

    # ── 百分比等比缩放 + 右边界贴合 ─────────────────────────────────
    def _reflow(self):
        if not self._ready or self._base_widths is None:
            return
        viewport_w = self.table.viewport().width()
        if viewport_w <= 0:
            return
        total = sum(self._base_widths)
        if total <= 0:
            return

        n = len(self._base_widths)
        factor = viewport_w / total
        # 1) 先按基准列宽等比缩放到目标宽度（保留浮点精度，便于后续分配余数）
        raw = [w * factor for w in self._base_widths]
        # 2) 上限每次都重新施加：caps 是视口宽的百分比，视口变化后必须重算，
        #    不能只在首次测量时算一次（否则放大窗口后内容列会无限膨胀）。
        capped = set()
        for c, ratio in self._width_caps.items():
            if c < n:
                cap = max(250, int(viewport_w * ratio))
                if raw[c] > cap:
                    raw[c] = float(cap)
                    capped.add(c)
        # 3) 硬下限（如全选表头按钮列）：先抬到下限并“锁定”，不再参与后续缩放。
        #    若留到最后才 clamp，总和会超出视口宽，右边缘出现留白/水平滚动条。
        locked = set()
        for c, mn in self._min_widths.items():
            if c < n and raw[c] < mn:
                raw[c] = float(mn)
                locked.add(c)
        # 4) 把差额（可能为正也可能为负）迭代分给仍有余量的列（未封顶/未锁定），
        #    使总和精确贴合视口宽。分配中触碰上限的列就地封顶，下一轮再分配剩余量。
        for _ in range(3):
            slack = viewport_w - sum(raw)
            if abs(slack) <= 0.5:
                break
            cand = []
            for c in range(n):
                if c in capped or c in locked:
                    continue
                ratio = self._width_caps.get(c)
                if ratio is not None and slack > 0:
                    if raw[c] >= max(250, int(viewport_w * ratio)):
                        capped.add(c)
                        continue
                cand.append(c)
            if not cand:
                break
            base_sum = sum(raw[c] for c in cand)
            if base_sum <= 0:
                if slack > 0:
                    for c in cand:
                        raw[c] = slack / len(cand)
                break
            scale = (base_sum + slack) / base_sum
            if scale <= 0:
                break
            for c in cand:
                raw[c] *= scale
                ratio = self._width_caps.get(c)
                if ratio is not None:
                    lim = float(max(250, int(viewport_w * ratio)))
                    if raw[c] > lim:
                        raw[c] = lim
                        capped.add(c)
        # 5) 向下取整后按最大余数法分配剩余像素；封顶/锁定列不参与，避免突破上下限
        widths = [int(w) for w in raw]
        rem = viewport_w - sum(widths)
        if rem > 0:
            order = sorted((c for c in range(n) if c not in capped and c not in locked),
                           key=lambda c: (-(raw[c] - widths[c]), c))
            if not order:
                order = list(range(n))
            for i in range(rem):
                widths[order[i % len(order)]] += 1
        self._resizing = True
        try:
            for c, w in enumerate(widths):
                self._header.resizeSection(c, w)
        finally:
            self._resizing = False
        self._last_reflow_w = viewport_w

    # ── 事件处理 ─────────────────────────────────────────────────────
    def _schedule_reflow(self):
        # 表格 Resize 事件触发时 viewport 宽度仍为旧值，需延迟到布局落定后再计算
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._do_deferred_reflow)

    def _do_deferred_reflow(self):
        self._pending = False
        self._reflow()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Resize:
            if obj is self.table:
                self._schedule_reflow()
            elif obj is self.table.viewport():
                # 仅当视口宽真的变化时才重排：resizeSection 本身可能切换水平滚动条，
                # 从而再次触发 viewport Resize —— 用宽度去重可避免自激循环。
                if self.table.viewport().width() != self._last_reflow_w:
                    self._schedule_reflow()
        return False
