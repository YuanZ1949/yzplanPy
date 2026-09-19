"""ui/adaptive_table.py: 让 QTableWidget 列宽自适应窗口的共享工具。

行为：
- 所有列都设为 Interactive（可手动拖拽调整列宽）。
- 记录用户调整后的列宽为「基准列宽」。
- 窗口/表格宽度变化时，对所有列宽按百分比等比缩放（不破坏用户的相对比例）。
- 右边界始终贴合窗口（缩放后微调最后一列吸收取整误差）。
- 首次显示时按表头/内容做一次性自适应初值，然后冻结为基准。
"""

from core.qt_bootstrap import import_qt
from ui.adaptive_table_filter import CELL_CONTENT_PAD, _AdaptiveFilter

_, QtCore, _, QtWidgets = import_qt()


def calc_cell_content_width(col_width: int, pad: int = CELL_CONTENT_PAD,
                            min_width: int = 40) -> int:
    """给定表格列总宽度，扣除单元格内边距后返回可渲染内容宽度。

    Parameters
    ----------
    col_width : int
        ``QTableWidget.columnWidth(col)`` 返回的列像素宽。
    pad : int
        水平内边距（左右合计），默认 ``CELL_CONTENT_PAD``。
    min_width : int
        返回值下限，避免折行计算收到过小宽度导致异常。
    """
    return max(min_width, col_width - pad)


def make_adaptive_table(table_widget, min_column_width=None, width_caps=None, min_widths=None,
                        persist_key=None, config=None):
    """让指定 QTableWidget 的列宽自适应窗口。返回过滤器对象（需持有以防被回收）。

    min_column_width: 最小列宽（默认 CELL_CONTENT_PAD + 24 = 40，已含单元格内边距）。
    width_caps: {列号: 该列最多占视口宽的比例 0~1}，用于折行/弹性列（如“内容”列），
    避免其按原始全文测宽后吃满窗口、挤压其余窄列导致内容被截断/换行。
    min_widths: {列号: 最小像素宽}，等比缩放后该列也不得低于此宽度（如全选表头按钮列）。
    persist_key + config: 同时提供时启用列宽持久化——用户拖拽列宽经 600ms 防抖写入
    配置（config.set(persist_key, [..])），下次创建时恢复；不传则行为不变。
    """
    return _AdaptiveFilter(table_widget, min_column_width=min_column_width,
                           width_caps=width_caps, min_widths=min_widths,
                           persist_key=persist_key, config=config)
