"""todo_notes QSS 构建器：下拉弹窗/编辑器/选项列胶囊样式（值全部来自主题令牌）。"""
from core.theme.tokens import sizing, theme_palette

def combo_popup_qss():
    """下拉弹窗（QAbstractItemView）规则。

    QComboBox 自身的 background 会被 Qt 样式表引擎拿去推导弹窗 view 的底色；
    不显式指定时弹窗会退化成黑底 + 近不可见文字（实测弹窗主色为纯黑、
    选项文字 alpha 仅 12/255），即「下拉栏背景黑色和字完全一致」。
    """
    p = theme_palette()
    return (
        f"QComboBox QAbstractItemView {{"
        f" background: {p['qss_menu_bg']};"
        f" color: {p['text_primary']};"
        f" border: 1px solid {p['qss_menu_border']};"
        f" selection-background-color: {p['qss_menu_sel_bg']};"
        f" selection-color: {p['white']}; }}"
    )


def editor_qss():
    """常驻编辑器 QSS：单元格内不画四边框，只画一条底部柔色底线，
    与表格行分隔线（table_gridline）一致，行样式整行等高（值全部来自主题令牌）。
    悬停反馈交给表格行背景（delegate 整行 hover），编辑器自身不再变框。
    三边用 transparent（而非 border:none）：QSS 引擎对 border:none + 半透明
    background 不按 box 模型绘制（实测渲染成纯黑），保留 1px 边框位激活 box。"""
    p = theme_palette()
    sz = sizing()
    return (
        f"QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{"
        f" background: {p['todo_editor_bg']};"
        f" border: 1px solid transparent;"
        f" border-bottom: 1px solid {p['table_gridline']};"
        f" border-radius: 0;"
        f" padding: {sz['todo_editor_padding_v']} {sz['todo_editor_padding']};"
        f" }}"
        # QDateEdit/QComboBox 内嵌的 QLineEdit 会被全局 QLineEdit 规则上底色，
        # 且近透明背景会被样式引擎推导成纯黑（实测其 palette Base 为黑），
        # 故显式透明化，让父控件自己的背景透出来。
        f"QDateEdit QLineEdit, QComboBox QLineEdit {{"
        f" background: transparent; border: none; padding: 0; }}"
        + combo_popup_qss()
    )


def badge_overlay_qss():
    """选项列（类别/优先级/状态）失焦态：控件彻底隐形，胶囊交给 delegate 绘制。

    旧观感 = delegate 画「贴文字的彩色圆角标签」，常驻 combo 只当交互层，
    因此必须无背景/无边框/无内边距/文字透明，否则会和 delegate 画的胶囊
    叠成双份。箭头由 drop-down 宽度归零隐藏（down-arrow 不再单独归零，
    避免详情弹窗等复用场景把箭头压成小点）。下拉弹窗仍需显式规则，
    否则黑底黑字。
    """
    return (
        f"QComboBox {{"
        f" background: transparent;"
        f" border: none;"
        f" padding: 0;"
        f" color: transparent; }}"
        f"QComboBox::drop-down {{ border: none; width: 0; }}"
        f"QComboBox QLineEdit {{"
        f" background: transparent; border: none; padding: 0; color: transparent; }}"
        + combo_popup_qss()
    )


def badge_edit_qss(color=None):
    """选项列聚焦态：显示为可读编辑器（保留手输新值能力），失焦后回到隐形胶囊。

    箭头由 drop-down 宽度归零隐藏（down-arrow 不再单独归零，避免详情弹窗
    等复用场景把箭头压成小点）；color 为选项色时用它做文字色。
    """
    p = theme_palette()
    sz = sizing()
    fg = color or p["text_primary"]
    return (
        f"QComboBox {{"
        f" background: {p['todo_editor_bg']};"
        f" border: 1px solid transparent;"
        f" border-bottom: 1px solid {p['table_gridline']};"
        f" border-radius: 0;"
        f" padding: {sz['todo_editor_padding_v']} {sz['todo_editor_padding']};"
        f" color: {fg}; }}"
        f"QComboBox::drop-down {{ border: none; width: 0; }}"
        f"QComboBox QLineEdit {{"
        f" background: transparent; border: none; padding: 0; color: {fg}; }}"
        + combo_popup_qss()
    )
