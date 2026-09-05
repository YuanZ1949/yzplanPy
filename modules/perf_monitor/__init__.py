# -*- coding: utf-8 -*-
"""性能监测模块：CPU/内存实时曲线、进程指标卡片、关键操作耗时统计、
函数采样器、线程栈与主线程卡死排查。"""
import collections
import math
import re
import time

from ..base import ModuleBase
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, StrongBodyLabel

_, QtCore, QtGui, QtWidgets = import_qt()

from .styles import (_theme_colors, _qcolor, _nice_ceil, _smooth_path,
                     _group_box_style, _ctrl_frame_style, _table_style,
                     _tabs_style)
from .proc import _PROC, _num_handles, _proc_resources
from .cards import (_IconBadge, _MetricCard, _make_metric_card,
                    _paint_metric_icon)
from .bar import _BarDelegate, _bar_text_color
from .proxy import _SortFilterProxy
from .chart import _LineChart
from .spark import _draw_spark
from .home import _HomePerfWidget, _make_home_widget
from .table import _NumItem, _make_perf_table, _populate_table
from .page import _make_page_widget
from .module import ENABLED_KEY, MODULE_INFO, Module

__all__ = [
    "ModuleBase", "BodyLabel", "StrongBodyLabel", "QtCore", "QtGui",
    "QtWidgets", "Module", "MODULE_INFO", "ENABLED_KEY",
    "_theme_colors", "_qcolor", "_nice_ceil", "_smooth_path",
    "_group_box_style", "_ctrl_frame_style", "_table_style", "_tabs_style",
    "_PROC", "_num_handles", "_proc_resources", "_IconBadge", "_MetricCard",
    "_make_metric_card", "_paint_metric_icon", "_BarDelegate", "_bar_text_color",
    "_SortFilterProxy", "_LineChart", "_draw_spark", "_HomePerfWidget",
    "_make_home_widget", "_NumItem", "_make_perf_table", "_populate_table",
    "_make_page_widget",
]