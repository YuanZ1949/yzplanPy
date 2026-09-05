"""todo_notes 模块：便签/待办事项管理，支持优先级、类别、截止日期、搜索筛选、内联编辑与复制。"""
import shutil
import sqlite3
from datetime import datetime, timedelta

from ..base import ModuleBase

from core.constants import DB_PATH
from core.perf import trace
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from ..todo_store import (
    _get_conn,
    add_todo,
    update_todo,
    delete_todo,
    get_todos,
    get_categories,
    get_todo_count,
)

from .constants import (
    PRIORITY_LABELS,
    PRIORITY_COLORS,
    CONTENT_MAX_LINES,
    CONTENT_COL_PAD,
    COL_CHECK,
    COL_TITLE,
    COL_CONTENT,
    COL_CATEGORY,
    COL_PRIORITY,
    COL_DUE,
    COL_STATUS,
    COL_CREATED,
)
from .module import MODULE_INFO, Module
from .home import _make_home_widget, _toggle_done, _home_context_menu
from .date_theme import _apply_date_theme
from .delegate import _TodoItemDelegate
from .select_all_header import _SelectAllHeader
from .page_widget import _make_page_widget
from .page_helpers import (_page_context_menu, _maybe_reset_done_on_content_change,
                           _TodoEditDialog)