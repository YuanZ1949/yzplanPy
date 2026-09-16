"""subtitle_widget 测试：构建、内容更新、透明度/字号、销毁、子进程冒烟。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def test_construct_and_set_content():
    _app()
    from modules.translator.subtitle_widget import SubtitleWidget
    w = SubtitleWidget()
    w.set_content("Hello", "你好")
    assert w._label_orig.text() == "Hello"
    assert w._label_trans.text() == "你好"
    w.close()


def test_window_flags():
    _app()
    from modules.translator.subtitle_widget import SubtitleWidget
    w = SubtitleWidget()
    flags = w.windowFlags()
    assert flags & QtCore.Qt.WindowStaysOnTopHint
    assert flags & QtCore.Qt.FramelessWindowHint
    assert flags & QtCore.Qt.Tool
    assert w.testAttribute(QtCore.Qt.WA_TranslucentBackground)
    w.close()


def test_set_opacity_clamps():
    _app()
    from modules.translator.subtitle_widget import SubtitleWidget
    w = SubtitleWidget()
    w.set_opacity(0.2)
    assert w._opacity == 0.5
    w.set_opacity(1.5)
    assert w._opacity == 1.0
    w.set_opacity(0.8)
    assert w._opacity == 0.8
    w.close()


def test_set_font_size_clamps():
    _app()
    from modules.translator.subtitle_widget import SubtitleWidget
    w = SubtitleWidget()
    w.set_font_size(100)
    assert w._font_size == 48
    w.set_font_size(5)
    assert w._font_size == 12
    w.set_font_size(30)
    assert w._font_size == 30
    w.close()


def test_pairs_capped():
    _app()
    from modules.translator.subtitle_widget import SubtitleWidget, _MAX_PAIRS
    w = SubtitleWidget()
    for i in range(_MAX_PAIRS + 5):
        w.set_content(f"orig{i}", f"trans{i}")
    assert len(w._pairs) == _MAX_PAIRS
    assert w._pairs[-1] == (f"orig{_MAX_PAIRS + 4}", f"trans{_MAX_PAIRS + 4}")
    assert w._label_orig.text() == f"orig{_MAX_PAIRS + 4}"
    w.close()


# ── 子进程冒烟：构造→set_content→销毁 ──────────────────────────

def test_subtitle_smoke_no_crash_subprocess():
    import subprocess
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_subtitle_widget.py::test_subtitle_smoke_no_crash_child", "-q"],
        timeout=60, capture_output=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )


def test_subtitle_smoke_no_crash_child():
    """子进程冒烟：构造→set_content→显示→销毁。"""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    from modules.translator.subtitle_widget import SubtitleWidget
    w = SubtitleWidget()
    w.set_content("Hello world", "你好世界")
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    w.close()
    w.deleteLater()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    print("SUBTITLE_SMOKE_OK")