"""todo_notes 日期编辑主题：_apply_date_theme。"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()


def _calendar_qss(p):
    """按全局调色板构建日历 QSS（明暗两套，全部颜色来自令牌）。"""
    if p["dark"]:
        return (
            "QCalendarWidget { background: %s; color: %s; }"
            "QCalendarWidget QWidget#qt_calendar_navigationbar { background: %s; }"
            "QCalendarWidget QToolButton { color: %s; background: transparent; }"
            "QCalendarWidget QAbstractItemView { background: %s; color: %s;"
            " selection-background-color: %s; selection-color: %s; }"
            "QCalendarWidget QTableView { background: %s; color: %s;}"
            "QCalendarWidget QHeaderView { background: %s; color: %s;}"
            "QCalendarWidget QSpinBox { background: %s; color: %s; }"
            "QCalendarWidget QMenu { background: %s; color: %s; }"
            % (p["calendar_bg"], p["text_primary"],
               p["calendar_nav_bg"],
               p["text_primary"],
               p["calendar_bg"], p["text_primary"],
               p["calendar_sel_bg"], p["calendar_sel_fg"],
               p["calendar_bg"], p["text_primary"],
               p["calendar_nav_bg"], p["text_primary"],
               p["calendar_ctrl_bg"], p["text_primary"],
               p["calendar_ctrl_bg"], p["text_primary"])
        )
    return (
        "QCalendarWidget QAbstractItemView { background: %s;"
        " selection-background-color: %s;"
        " selection-color: %s; color: %s; }"
        % (p["calendar_bg"], p["calendar_sel_bg"], p["calendar_sel_fg"],
           p["text_primary"])
    )


def _apply_date_theme(date_edit):
    """让 QDateEdit 弹出的日历与主程序主题一致（避免黑底黑字混在一起）。"""
    from core.theme.tokens import theme_palette
    p = theme_palette()

    fg = QtGui.QColor(p["text_primary"])
    bg = QtGui.QColor(p["calendar_bg"])
    qss = _calendar_qss(p)
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
                pal.setColor(QtGui.QPalette.HighlightedText,
                             QtGui.QColor(p["calendar_sel_fg"]))
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
    date_edit.setStyleSheet("QDateEdit { color: %s; }" % p["text_primary"])
