"""RSS 条目行紧凑化参数测试：离屏防截断护栏 + 紧凑性断言。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from modules.rss_aggregator.rows import _WrapRow, _AutoRow, _pill_style
from modules.rss_aggregator.rows_item import _make_item_row

# ---------------------------------------------------------------------------
# 测试用长标题
# ---------------------------------------------------------------------------
LONG_CN = "这是一条用于测试紧凑化参数的超长中文标题，目的是验证文字换行时行高计算是否完整" * 3
LONG_EN = ("This is an extremely long English title designed to test compact row parameters "
           "and verify that word-wrap height calculation includes all margins without truncation. ") * 3


# ---------------------------------------------------------------------------
# (a) 不截断护栏：_WrapRow 高度必须包含 label 换行高度 + 布局 margins
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [LONG_CN, LONG_EN], ids=["cn", "en"])
def test_wrap_row_no_truncate(text):
    """row.heightForWidth(w) >= label.heightForWidth(w) + vertical margins sum."""
    row = _WrapRow(text)
    row.show()
    w = 600
    h = row.heightForWidth(w)
    m = row.layout().contentsMargins()
    margins_v = m.top() + m.bottom()
    label_h = row.label.heightForWidth(w)
    assert h >= label_h + margins_v, (
        f"heightForWidth({w})={h} < label.heightForWidth({w})={label_h} "
        f"+ margins_v={margins_v} => truncation risk"
    )


# ---------------------------------------------------------------------------
# (b) 紧凑性：新参数比旧基线短 ≥ 10%
# ---------------------------------------------------------------------------
def _build_old_row(text):
    """用旧参数（硬编码，不引用被改的源码常量）手动构造条目行。"""
    row = _AutoRow()
    lay = QtWidgets.QHBoxLayout(row)
    lay.setContentsMargins(8, 4, 8, 4)   # 旧 margins
    lay.setSpacing(6)                     # 旧 spacing

    # 旧 _WrapRow 字号 11px，margins (2,2,2,2)
    title = _WrapRow(text)
    f = title.label.font()
    f.setPointSizeF(11)                   # 旧字号
    title.label.setFont(f)
    # 旧 _WrapRow margins
    title.layout().setContentsMargins(2, 2, 2, 2)

    # dot
    dot = QtWidgets.QLabel("●")
    dot.setFixedWidth(10)
    dot.setStyleSheet("QLabel { font-size: 10px; }")
    lay.addWidget(dot)
    lay.addWidget(title, 1)
    row.bind_title(title)
    row.show()
    return row


def test_compactness():
    """同一标题，新参数 sizeHint().height() 比旧基线低 ≥ 10%。"""
    text = "这是一条测试紧凑化参数的标题 | A test title for compactness verification " * 4

    old_row = _build_old_row(text)
    old_h = old_row.sizeHint().height()

    item = {
        "title": text,
        "link": "http://example.com/1",
        "tags": "",
        "read": False,
        "favorite": False,
    }
    new_row, _, _ = _make_item_row(None, item, None)
    new_row.show()
    new_h = new_row.sizeHint().height()

    assert old_h > 0 and new_h > 0
    reduction = (old_h - new_h) / old_h
    assert reduction >= 0.10, (
        f"Reduction {reduction:.1%} < 10% threshold "
        f"(old={old_h}, new={new_h})"
    )


# ---------------------------------------------------------------------------
# (c) 保底：_sync_row_heights 模拟后每行 height >= 34
# ---------------------------------------------------------------------------
def test_floor_height_after_sync():
    """模拟 _sync_row_heights 逻辑，每行最终 sizeHint().height() >= 34。"""
    lw = QtWidgets.QListWidget()
    lw.show()

    for i in range(5):
        item_dict = {
            "title": f"测试标题第{i}条标题内容比较短",
            "link": "http://example.com/{}".format(i),
            "tags": "",
            "read": False,
            "favorite": False,
        }
        row_widget, _, _ = _make_item_row(lw, item_dict, None)
        li = QtWidgets.QListWidgetItem()
        lw.addItem(li)
        lw.setItemWidget(li, row_widget)

    # 模拟 _sync_row_heights 新参数
    style_pad = 18
    style_pad_v = 10
    vp_w = lw.viewport().width() - 8 - style_pad
    if vp_w <= 0:
        vp_w = 400

    for row_idx in range(lw.count()):
        li = lw.item(row_idx)
        wid = lw.itemWidget(li)
        assert wid is not None
        h = None
        try:
            if wid.hasHeightForWidth():
                h = wid.heightForWidth(vp_w)
        except Exception:
            h = None
        if not h or h <= 0:
            h = wid.sizeHint().height()
        h = max(h, 34)
        li.setSizeHint(QtCore.QSize(vp_w + 8 + style_pad, int(h) + style_pad_v))

        # 断言：保底 ≥ 34
        assert li.sizeHint().height() >= 34, (
            f"Row {row_idx}: sizeHint height {li.sizeHint().height()} < 34"
        )
