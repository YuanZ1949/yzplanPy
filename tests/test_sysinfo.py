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


def test_each_row_has_selectable_value_label():
    """两列表单：值单元格只读、可选中复制、自动换行、行高来自令牌。"""
    from qfluentwidgets import GroupHeaderCardWidget
    from core.theme.tokens import sizing
    from modules.sys_info import collect_info
    w = _make_widget()
    assert not w.findChildren(GroupHeaderCardWidget), "不应再包含分组卡片"
    value_labels = [l for l in w.findChildren(QtWidgets.QLabel)
                    if l.property("sysinfo_key")]
    rendered = {l.property("sysinfo_key") for l in value_labels}
    assert rendered == set(collect_info()), "21 个键应全部渲染"
    for label in value_labels:
        assert label.text().strip(), "值不应为空"
        assert label.wordWrap(), "值应自动换行"
        flags = label.textInteractionFlags()
        assert flags & QtCore.Qt.TextInteractionFlag.TextSelectableByMouse, "应可鼠标选中"
        assert flags & QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard, "应可键盘选中"
        assert label.minimumHeight() == sizing()["sysinfo_row_height"], \
            "行高应来自 sizing 令牌"


def test_page_is_scrollable():
    """整页可滚动（QScrollArea），适配小窗口。"""
    w = _make_widget()
    scrolls = w.findChildren(QtWidgets.QScrollArea)
    assert scrolls, "页面应包含 QScrollArea"
    assert scrolls[0].widgetResizable(), "滚动区应随窗口自适应"


def test_page_has_refresh_and_copy_buttons():
    """顶部有「刷新」主按钮与「复制全部」按钮（来自 make_button 工厂）。"""
    from core.theme.tokens import theme_palette
    w = _make_widget()
    texts = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert "刷新" in texts
    assert "复制全部" in texts
    p = theme_palette()
    refresh = [b for b in w.findChildren(QtWidgets.QPushButton)
               if b.text() == "刷新"]
    assert refresh and p["accent"] in refresh[0].styleSheet(), \
        "「刷新」按钮应来自 make_button（QSS 含 accent 令牌色）"


# 动态实时量：两次采样间必然波动（已用/剩余、累计 IO 计数），
# 刷新对比时允许其值变化；其余字段为静态信息，必须完全一致。
_DYNAMIC_KEYS = {"系统盘", "内存使用", "磁盘IO"}


def _info_rows(w):
    """把表单值单元格（带 sysinfo_key 属性）收集为 {键: 值} 映射。"""
    out = {}
    for l in w.findChildren(QtWidgets.QLabel):
        key = l.property("sysinfo_key")
        if key:
            out[key] = l.text()
    return out


def test_refresh_button_rebuilds_content():
    """点击「刷新」重新采集并填充表单内容，不崩溃。"""
    w = _make_widget()
    before = _info_rows(w)
    for b in w.findChildren(QtWidgets.QPushButton):
        if b.text() == "刷新":
            b.click()
            break
    after = _info_rows(w)
    # 刷新会重新采集数据源：字段（键）集合必须一致；静态字段值须一致；
    # 动态实时量（系统盘/内存使用/磁盘IO）允许在两次采样间波动。
    assert set(after) == set(before)
    for k in before:
        if k not in _DYNAMIC_KEYS:
            assert after[k] == before[k], f"静态字段「{k}」刷新后不应变化"


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