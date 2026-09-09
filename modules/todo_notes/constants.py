"""todo_notes 常量：优先级标签/颜色、内容列限制、表格列索引。"""
PRIORITY_LABELS = {0: "低", 1: "中", 2: "高", 3: "紧急"}
PRIORITY_COLORS = {0: "#888", 1: "#e67e22", 2: "#e74c3c", 3: "#c0392b"}

CONTENT_MAX_LINES = 6   # 内容列在普通显示时最多展示的前几行（编辑时展开全部）
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
