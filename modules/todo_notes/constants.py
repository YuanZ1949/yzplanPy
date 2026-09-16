"""todo_notes 常量：优先级标签/颜色、内容列限制、表格列索引。"""
from core.theme.tokens import sizing, theme_palette

PRIORITY_LABELS = {0: "低", 1: "中", 2: "高", 3: "紧急"}


def priority_colors():
    """优先级徽章/文字色（主题感知，值来自全局令牌）。"""
    p = theme_palette()
    return {0: p["text_secondary"], 1: p["warning"], 2: p["danger"],
            3: p["todo_priority_urgent"]}


def status_color(status):
    """状态徽章/文字色：优先状态自定义 color，回退 todo_option_palette 按 status_id 取色。"""
    p = theme_palette()
    color = (status or {}).get("color")
    if color:
        return color
    palette = p["todo_option_palette"]
    sid = (status or {}).get("id", 0)
    return palette[sid % len(palette)]


def editor_qss():
    """常驻编辑器 QSS：边框 + 悬停高亮（值全部来自主题令牌）。"""
    p = theme_palette()
    sz = sizing()
    bw = sz["todo_editor_border_width"]
    return (
        f"QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{"
        f" background: {p['todo_editor_bg']};"
        f" border: {bw}px solid {p['todo_editor_border']};"
        f" border-radius: 0;"
        f" padding: {sz['todo_editor_padding']};"
        f" }}"
        f"QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateEdit:hover {{"
        f" border-color: {p['todo_editor_border_hover']};"
        f" }}"
    )


def status_combo_qss(color):
    """状态列下拉框 QSS：文字色跟随状态 color（值来自令牌/状态自定义色）。"""
    p = theme_palette()
    sz = sizing()
    bw = sz["todo_editor_border_width"]
    return (
        f"QComboBox {{ background: {p['todo_editor_bg']};"
        f" border: {bw}px solid {p['todo_editor_border']};"
        f" border-radius: 0;"
        f" padding: {sz['todo_editor_padding']};"
        f" color: {color}; }}"
        f"QComboBox:hover {{ border-color: {p['todo_editor_border_hover']}; }}"
    )

CONTENT_SAFE_MAX_LINES = 200  # 显示/编辑统一安全上限，非显示截断上限
CONTENT_COL_PAD = 16    # 内容列文本左右内边距（与 ui/adaptive_table.py CELL_CONTENT_PAD 对齐）

# 表格列索引
COL_CHECK = 0      # 复选框（多选批量操作）
COL_TITLE = 1
COL_CONTENT = 2
COL_CATEGORY = 3
COL_PRIORITY = 4
COL_DUE = 5
COL_STATUS = 6
COL_CREATED = 7
