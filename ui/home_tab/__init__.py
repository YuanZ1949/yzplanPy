"""主页选项卡：QGraphicsView 画布，组件可拖拽移动、边框拉伸、
拖动切换顺序、点击添加弹出方块选择面板。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)

_, QtCore, QtGui, QtWidgets = import_qt()

from .constants import (
    _DEF_W, _DEF_H, _MIN_W, _MIN_H, _GAP, _EDGE,
    _STRETCH_THRESHOLD, _DRAG_THRESHOLD,
)
from .flow import _FlowLayout
from .canvas import _CanvasView
from .proxy import _Proxy
from .handle import _Handle
from .picker import _AddPopup, _PickCard
from .tab_core import HomeTab
from .tab_layout import HomeTab
from .tab_layout2 import HomeTab
from .tab_config import HomeTab