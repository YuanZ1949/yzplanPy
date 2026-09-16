import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.sys_info import _cpu_brand, collect_info


def _make_qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _make_widget():
    _make_qapp()
    from modules.sys_info import _make_info_widget
    return _make_info_widget(None)


def test_collect_info_keys():
    info = collect_info()
    for key in ("系统", "处理器", "内存总量", "GPU", "主机名"):
        assert key in info
    assert len(info) >= 8


def test_collect_info_extended_keys():
    """Task 10: collect_info 追加 Python/网络/启动时间/IO 等新字段。"""
    info = collect_info()
    for key in ("Python版本", "PySide6版本", "qfluentwidgets版本",
                "网络适配器", "系统启动时间", "磁盘IO"):
        assert key in info
        assert info[key], f"{key} 不应为空"
    # 新字段必须追加在原有字段之后
    keys = list(info)
    assert keys.index("Python版本") > keys.index("系统盘")


def test_cpu_brand_nonempty_no_wmic():
    """Task 11: _cpu_brand 返回非空字符串，且不再依赖 wmic。"""
    name = _cpu_brand()
    assert isinstance(name, str)
    assert name.strip()
    assert "wmic" not in name.lower()


# ── Task 12: qfluentwidgets 分组卡片界面 ──────────────────────────────

def test_page_has_group_cards():
    """配置信息页包含 硬件/系统/网络/软件 四张分组卡片。"""
    from qfluentwidgets import GroupHeaderCardWidget
    w = _make_widget()
    cards = w.findChildren(GroupHeaderCardWidget)
    titles = [c.getTitle() for c in cards]
    for name in ("硬件", "系统", "网络", "软件"):
        assert name in titles


def test_each_card_has_readonly_text_edit():
    """每张卡片内含只读、自动换行、最小高度 80 的 PlainTextEdit。"""
    from qfluentwidgets import GroupHeaderCardWidget, PlainTextEdit
    w = _make_widget()
    cards = w.findChildren(GroupHeaderCardWidget)
    assert len(cards) == 4
    for card in cards:
        edits = card.findChildren(PlainTextEdit)
        assert len(edits) == 1
        edit = edits[0]
        assert edit.isReadOnly()
        assert edit.minimumHeight() >= 80
        assert edit.toPlainText().strip()


def test_page_has_refresh_and_copy_buttons():
    """顶部有「刷新」PrimaryPushButton 与「复制全部」PushButton。"""
    from qfluentwidgets import PrimaryPushButton, PushButton
    w = _make_widget()
    texts = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert "刷新" in texts
    assert "复制全部" in texts
    assert len(w.findChildren(PrimaryPushButton)) >= 1
    assert len(w.findChildren(PushButton)) >= 1


# 动态实时量：两次采样间必然波动（已用/剩余、累计 IO 计数），
# 刷新对比时允许其值变化；其余字段为静态信息，必须完全一致。
_DYNAMIC_KEYS = {"系统盘", "内存使用", "磁盘IO"}


def _info_lines(text):
    """把卡片 PlainTextEdit 的整段文本拆成非空行（每行形如「键: 值」）。"""
    return [ln for ln in text.splitlines() if ln.strip()]


def test_refresh_button_rebuilds_content():
    """点击「刷新」重新采集并填充卡片内容，不崩溃。"""
    w = _make_widget()
    from qfluentwidgets import PlainTextEdit
    before = [_info_lines(e.toPlainText()) for e in w.findChildren(PlainTextEdit)]
    for b in w.findChildren(QtWidgets.QPushButton):
        if b.text() == "刷新":
            b.click()
            break
    after = [_info_lines(e.toPlainText()) for e in w.findChildren(PlainTextEdit)]
    # 刷新会重新采集数据源：字段（键）集合必须一致；静态字段值须一致；
    # 动态实时量（系统盘/内存使用/磁盘IO）允许在两次采样间波动。
    assert len(after) == len(before)
    for a_lines, b_lines in zip(after, before):
        keys_a = {ln.split(":", 1)[0] for ln in a_lines}
        keys_b = {ln.split(":", 1)[0] for ln in b_lines}
        assert keys_a == keys_b
        value_of = {ln.split(":", 1)[0]: ln for ln in a_lines}
        for ln_b in b_lines:
            key = ln_b.split(":", 1)[0]
            if key not in _DYNAMIC_KEYS:
                assert value_of[key] == ln_b, f"静态字段「{key}」刷新后不应变化"


def test_copy_button_puts_all_info_on_clipboard():
    """点击「复制全部」把全部信息以「键: 值」写入剪贴板（动态实时量允许波动）。"""
    w = _make_widget()
    for b in w.findChildren(QtWidgets.QPushButton):
        if b.text() == "复制全部":
            b.click()
            break
    text = QtWidgets.QApplication.clipboard().text()
    info = collect_info()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == len(info), \
        f"剪贴板行数 {len(lines)} 应 == 字段数 {len(info)}"
    value_of = {ln.split(":", 1)[0]: ln for ln in lines}
    for k, v in info.items():
        assert k in value_of, f"剪贴板缺少键「{k}」"
        if k not in _DYNAMIC_KEYS:
            assert value_of[k] == f"{k}: {v}", f"静态字段「{k}」不应变化"


def test_page_open_render_close_no_crash_subprocess():
    """Subprocess isolation: 打开→渲染→关闭配置信息页 (0xC0000005 guard)。"""
    import subprocess
    from pathlib import Path
    child_name = "test_page_open_render_close_no_crash_child"
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         f"tests/test_sysinfo.py::{child_name}",
         "-q"],
        timeout=60,
        capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode())
        print("STDERR:", result.stderr.decode())
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode()}\nstderr: {result.stderr.decode()}"
    )


def test_page_open_render_close_no_crash_child():
    """Child: 打开→渲染→关闭配置信息页，无崩溃。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from modules.sys_info import _make_info_widget

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    w = _make_info_widget(None)
    w.show()
    app.processEvents()
    assert w.findChildren(QtWidgets.QPushButton)
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    print("SYSINFO_PAGE_OK")