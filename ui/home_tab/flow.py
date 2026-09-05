"""home_tab.flow: 变宽自适应流式布局（_FlowLayout）。"""
from .constants import _MIN_W, _STRETCH_THRESHOLD

class _FlowLayout:
    """变宽自适应流式布局：按各自宽度贪心换行，填充度较高的行自动拉伸填满容器。"""

    def __init__(self, gap=12, margin=10):
        self.gap = gap
        self.margin = margin

    def _row_height(self, row):
        return max((h for _, _, h in row), default=0)

    def compute(self, items, container_width):
        """
        items: [(cid, width, height)]  按 order 排列
        返回: {cid: (x, y, actual_w, actual_h)}, total_height
        """
        available = max(1, container_width - 2 * self.margin)

        rows = []
        cur = []
        cur_w = 0.0
        for cid, width, height in items:
            w = max(_MIN_W, int(width))
            if cur and cur_w + self.gap + w > available:
                rows.append(cur)
                cur = []
                cur_w = 0.0
            cur.append((cid, w, height))
            cur_w += w + (self.gap if cur_w else 0)

        if cur:
            rows.append(cur)

        positions = {}
        y = 0.0
        for row in rows:
            row_w = sum((w for _, w, _ in row)) + self.gap * (len(row) - 1)
            fill_rate = row_w / available if available else 0
            if fill_rate >= _STRETCH_THRESHOLD and row_w < available:
                extra = available - row_w
                x = self.margin
                for cid, w, h in row:
                    scale = w / row_w if row_w else 0
                    sw = w + extra * scale
                    positions[cid] = (int(x), int(y), int(sw), h)
                    x += sw + self.gap
            else:
                x = self.margin
                for cid, w, h in row:
                    positions[cid] = (int(x), int(y), w, h)
                    x += w + self.gap
            y += self._row_height(row) + self.gap

        total_h = y if y else 0
        return positions, int(total_h)
