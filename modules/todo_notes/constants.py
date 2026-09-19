"""todo_notes 常量：优先级标签/颜色、内容列限制、表格列索引。"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from ..todo_store import get_categories, get_option_color

_, QtCore, QtGui, QtWidgets = import_qt()

PRIORITY_LABELS = {0: "低", 1: "中", 2: "高", 3: "紧急"}

# 选项颜色存储列名（todo_option_colors 表，todo 16 多颜色）
COLOR_COL_PRIORITY = "priority"
COLOR_COL_STATUS = "status"
COLOR_COL_CATEGORY = "category"


def priority_colors():
    """优先级徽章/文字色（主题感知，值来自全局令牌）。"""
    p = theme_palette()
    return {0: p["text_secondary"], 1: p["warning"], 2: p["danger"],
            3: p["todo_priority_urgent"]}


def priority_color(val):
    """优先级色：存储色优先，回落 priority_colors() 令牌色（默认值语义不变）。"""
    stored = get_option_color(COLOR_COL_PRIORITY, str(val))
    if stored:
        return stored
    _pc = priority_colors()
    return _pc.get(val, _pc[0])


def status_color(status):
    """状态徽章/文字色：优先状态自定义 color，回退 todo_option_palette 按 status_id 取色。"""
    p = theme_palette()
    color = (status or {}).get("color")
    if color:
        return color
    palette = p["todo_option_palette"]
    sid = (status or {}).get("id", 0)
    return palette[sid % len(palette)]


def category_color(category, index=None):
    """类别色：存储色优先，回落 todo_option_palette 按类别序号循环取色。"""
    if not category:
        return None
    stored = get_option_color(COLOR_COL_CATEGORY, category)
    if stored:
        return stored
    p = theme_palette()
    palette = p["todo_option_palette"]
    if index is None:
        try:
            index = get_categories().index(category)
        except ValueError:
            index = 0
    return palette[index % len(palette)]


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


CONTENT_SAFE_MAX_LINES = 200  # 显示/编辑统一安全上限，非显示截断上限

# QPlainTextEdit 视口比「文档高度 + chrome」恰好多 1px 才会把滚动范围归零
# （否则行高 == 文档+chrome 时仍能滚出半行）。行高统一公式加此 slack。
# 行高 slack：保证内容编辑器视口比文档实际高度多出余量，使滚动范围归零。
# =2 的理由（实测 Microsoft YaHei 9，真实 QPA 与 offscreen 一致）：
#   chrome 已精确覆盖 padding+border+docMargin，QFontMetrics 整数 lineSpacing
#   已把浮点行高（15.828px）向上取整到 16px；剩最后一环是 QTableWidget 会把
#   cellWidget 高度压成 rowHeight-1（表格布局吃掉 1px），导致 viewport 少 1px、
#   滚动范围恒为 1。slack=2 补偿该 1px 后，n×(sp)+chrome+2 恰好使 vbar.max==0
#   （临界扫描：n=1/3/5/8 全部 公式值+1 → max==0）。注意不可再加每行余量
#   （n×(sp+1) 会在多行时累积出整行不可编辑的空白）。
CONTENT_FIT_SLACK = 2

# 选项下拉（状态/类别）的「自定义…」哨兵项：选中后进入编辑模式输入新名，
# 提交时自动落库。itemData 用它标记，避免与真实选项的 id/文本混淆。
CUSTOM_OPTION_LABEL = "自定义…"
CUSTOM_OPTION_DATA = "__custom__"


# ---------------------------------------------------------------------------
# 内容列行高统一计算
# 编辑器垂直 chrome = 上下 (边框 + 内边距 + 文档边距)，全部由令牌派生，
# 使行高公式、折行宽度与 editor_qss() 的 padding 永远不会漂移。
# ---------------------------------------------------------------------------

def _editor_chrome_one_side():
    """编辑器垂直方向单侧 chrome（边框 + 纵向内边距 + 文档边距）。

    纵向内边距用 todo_editor_padding_v（比横向小），行高随之收紧，
    消除每行文字下方≈1 行的空白带。
    """
    sz = sizing()
    return (sz["todo_editor_border_width"] + sz["todo_editor_padding_v_px"]
            + sz["todo_editor_doc_margin"])


def _editor_frame_one_side():
    """编辑器水平方向单侧装饰宽（边框 + 内边距）。"""
    sz = sizing()
    return sz["todo_editor_border_width"] + sz["todo_editor_padding_px"]


def editor_text_width(col_width):
    """编辑器每行实际可用的折行宽（像素）。

    实测 QPlainTextEdit（真实 QPA + Microsoft YaHei 9，20 组对照）折行基准为
    viewport 宽再扣 2×文档边距：行宽 = widget − 2×(border+padding) − 2×docMargin。
    表格内 cellWidget 又比列宽吃 1px → 可用宽 = col_w − 2×frame − 2×docMargin − 1。
    估算宽若比实际宽 1px，wrapped_line_count 会多折 1 行 → 行高虚高一整行空白。
    """
    sz = sizing()
    return max(10, int(col_width) - 1 - 2 * _editor_frame_one_side()
               - 2 * sz["todo_editor_doc_margin"])


def editor_chrome_height():
    """编辑器垂直 chrome（上下边框 + 内边距 + 文档边距）。"""
    return 2 * _editor_chrome_one_side()


def wrapped_line_count(text, font, width):
    """按 QPlainTextEdit 同引擎统计折行数（QTextLayout + WrapAtWordBoundaryOrAnywhere）。

    贪心逐字符折行会在词边界处少算行（如 "hello world" 窄宽下编辑器实际 2 行），
    故必须用 QTextLayout 逐行 createLine 才能与编辑器渲染一致。
    """
    if not text:
        return 1
    total = 0
    for para in str(text).split("\n"):
        if para == "":
            total += 1
            continue
        layout = QtGui.QTextLayout(para, font)
        opt = QtGui.QTextOption()
        opt.setWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(opt)
        layout.beginLayout()
        n = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            n += 1
        layout.endLayout()
        total += max(1, n)
    return max(1, total)


def content_editor_font():
    """内容编辑器实际渲染字体（行高公式必须与之一致）。

    编辑器套用 editor_qss() 后，字体由 QSS 固定为创建时字体（实测 setFont 无效）；
    而 QTableWidget 的字体在 polish 后会漂移为 "Microsoft YaHei UI"（行距 15，
    编辑器仍为 Microsoft YaHei 行距 16）。若用 table.font() 计算行高，多行行高
    每行会少 1px，累计出现滚动范围与末行截断，故统一取应用字体。
    """
    app = QtWidgets.QApplication.instance()
    return app.font() if app is not None else QtGui.QFont()


def content_row_height(text, col_width):
    """内容列统一行高：min(折行数, 上限) * lineSpacing + 编辑器垂直 chrome + slack。

    slack（CONTENT_FIT_SLACK=2）保证编辑器视口比文档实际高度多 2px，
    使行高与编辑态完全不再产生滚动范围（需求：完全不用滚动）。
    字体取 content_editor_font()（编辑器真实渲染字体），不得改用 table.font()：
    表格字体在 polish 后漂移为 UI 变体（行距 15 vs 16），会让多行行高不足。
    """
    font = content_editor_font()
    fm = QtGui.QFontMetrics(font)
    count = wrapped_line_count(text, font, editor_text_width(col_width))
    lines = min(max(1, count), CONTENT_SAFE_MAX_LINES)
    return lines * fm.lineSpacing() + editor_chrome_height() + CONTENT_FIT_SLACK

# 表格列索引
COL_CHECK = 0      # 复选框（多选批量操作）
COL_TITLE = 1
COL_CONTENT = 2
COL_CATEGORY = 3
COL_PRIORITY = 4
COL_DUE = 5
COL_STATUS = 6
COL_CREATED = 7
