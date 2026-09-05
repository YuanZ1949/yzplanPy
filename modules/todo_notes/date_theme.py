"""todo_notes 日期编辑主题：_apply_date_theme。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
def _apply_date_theme(date_edit):
    """让 QDateEdit 弹出的日历与主程序主题一致（避免黑底黑字混在一起）。"""
    from core.theme import resolve_dark
    dark = resolve_dark("auto")

    def _fg_bg():
        if dark:
            return QtGui.QColor(0xe6, 0xe6, 0xe6), QtGui.QColor(0x1e, 0x1e, 0x1e)
        return QtGui.QColor(0x1a, 0x1a, 0x1a), QtGui.QColor(0xff, 0xff, 0xff)

    fg, bg = _fg_bg()
    qss = None
    if dark:
        qss = (
            "QCalendarWidget { background: #1e1e1e; color: #e6e6e6; }"
            "QCalendarWidget QWidget#qt_calendar_navigationbar { background: #232323; }"
            "QCalendarWidget QToolButton { color: #e6e6e6; background: transparent; }"
            "QCalendarWidget QAbstractItemView { background: #1e1e1e; color: #e6e6e6;"
            " selection-background-color: #3a6ea5; selection-color: #ffffff; }"
            "QCalendarWidget QTableView { background: #1e1e1e; color: #e6e6e6;}"
            "QCalendarWidget QHeaderView { background: #232323; color: #e6e6e6;}"
            "QCalendarWidget QSpinBox { background: #2b2b2b; color: #e6e6e6; }"
            "QCalendarWidget QMenu { background: #2b2b2b; color: #e6e6e6; }"
        )
    else:
        qss = (
            "QCalendarWidget QAbstractItemView { selection-background-color: #d9e7f7;"
            " selection-color: #1a1a1a; color: #1a1a1a; }"
        )
    try:
        cal = date_edit.calendarWidget()
        if cal is None:
            return

        def _paint(w):
            # 递归为日历内每个控件设置与主题一致的调色板，兜底 QSS 渲染不到的内部件
            try:
                pal = w.palette()
                pal.setColor(QtGui.QPalette.Window, bg)
                pal.setColor(QtGui.QPalette.Base, bg)
                pal.setColor(QtGui.QPalette.Text, fg)
                pal.setColor(QtGui.QPalette.WindowText, fg)
                pal.setColor(QtGui.QPalette.ButtonText, fg)
                pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(0xff, 0xff, 0xff))
                pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(0x8c, 0x8c, 0x8c))
                w.setPalette(pal)
            except Exception:
                pass
            for child in w.findChildren(QtWidgets.QWidget):
                _paint(child)

        applied = [False]

        def _apply():
            if qss:
                cal.setStyleSheet(qss)
                cal.setMinimumSize(320, 260)
            _paint(cal)  # 递归应用到当前所有子控件
            applied[0] = True

        _apply()

        # 日历的内部视图可能在首次弹出时才创建；每次弹出（Show）都重新应用主题，
        # 兜底 QSS 渲染不到的内部件，避免黑底黑字混在一起。
        class _Refilter(QtCore.QObject):
            def eventFilter(self, watched, ev):
                if ev.type() == QtCore.QEvent.Show:
                    _apply()
                return False

        _filter = _Refilter(cal)
        cal.installEventFilter(_filter)
        date_edit.setProperty("_date_theme_filter", _filter)  # 防止被回收
    except Exception:
        pass
    # 使 QDateEdit 自身的文本在暗色下可读
    date_edit.setStyleSheet(
        "QDateEdit { color: #e6e6e6; }" if dark else "QDateEdit { color: #1a1a1a; }"
    )
