"""translator 模块页测试：三栏布局、翻译流程、语音、历史、子进程冒烟。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from qfluentwidgets import ComboBox


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


class _Owner:
    pass


def _make_page():
    _app()
    from modules.translator.page import _make_page_widget
    w = _make_page_widget(_Owner(), None)
    w.resize(1000, 700)
    w.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    return w


def _translate_btn(w):
    return [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "翻译"][0]


def _edits(w):
    return w.findChildren(QtWidgets.QPlainTextEdit)


def _wait_until(cond, timeout=3.0):
    """泵事件循环直到条件成立（异步翻译结果经信号回主线程后生效）。"""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        QtWidgets.QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


# ── 三栏布局 ────────────────────────────────────────────────────

def test_page_builds_three_columns():
    w = _make_page()
    frames = w.findChildren(QtWidgets.QFrame)
    assert len(frames) >= 3  # 三栏卡片
    combos = w.findChildren(ComboBox)
    assert len(combos) == 3  # 源语言 / 目标语言 / provider
    buttons = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    for label in ("翻译", "复制结果", "开始", "停止", "显示悬浮字幕"):
        assert label in buttons, f"缺少按钮 {label}"
    w.close()


def test_page_has_auto_detect_src():
    w = _make_page()
    combos = w.findChildren(ComboBox)
    assert combos[0].itemData(0) == "auto"
    assert combos[0].itemText(0) == "自动检测"
    w.close()


def test_page_provider_dropdown_persists(monkeypatch):
    import modules.translator.llm_config as llm_cfg
    saved = []
    monkeypatch.setattr(llm_cfg, "get_provider", lambda: "google")
    monkeypatch.setattr(llm_cfg, "set_provider", lambda v: saved.append(v))
    w = _make_page()
    combos = w.findChildren(ComboBox)
    prov = combos[2]
    assert prov.itemData(0) == "google"
    assert prov.itemData(1) == "llm"
    prov.setCurrentIndex(1)
    assert saved == ["llm"]
    w.close()


# ── 翻译流程 ────────────────────────────────────────────────────

def test_page_translate_flow(monkeypatch):
    import modules.translator.page as page_mod
    monkeypatch.setattr(
        page_mod, "translate_text",
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "你好")
    w = _make_page()
    edits = _edits(w)
    edits[0].setPlainText("Hello")
    _translate_btn(w).click()
    assert _wait_until(lambda: edits[1].toPlainText() == "你好")
    w.close()


def test_page_translate_empty_input_no_crash(monkeypatch):
    import modules.translator.page as page_mod
    monkeypatch.setattr(page_mod, "translate_text", lambda *a, **k: "X")
    w = _make_page()
    _translate_btn(w).click()  # 空输入：不应调用翻译
    assert _edits(w)[1].toPlainText() == ""
    w.close()


def test_page_swap_languages():
    w = _make_page()
    combos = w.findChildren(ComboBox)
    src, dst = combos[0], combos[1]
    src.setCurrentIndex(2)  # en
    dst.setCurrentIndex(1)  # zh
    btn = [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "⇄"][0]
    btn.click()
    assert src.currentData() == "zh"
    assert dst.currentData() == "en"
    w.close()


def test_page_copy_target(monkeypatch):
    w = _make_page()
    edits = _edits(w)
    edits[1].setPlainText("你好")
    copied = []
    monkeypatch.setattr(
        QtWidgets.QApplication.clipboard(), "setText", lambda t: copied.append(t))
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "复制结果"][0]
    btn.click()
    assert copied == ["你好"]
    w.close()


def test_page_history_records_last_20(monkeypatch):
    import modules.translator.page as page_mod
    monkeypatch.setattr(
        page_mod, "translate_text",
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "译:" + text)
    w = _make_page()
    edits = _edits(w)
    btn = _translate_btn(w)
    for i in range(25):
        edits[0].setPlainText(f"text{i}")
        btn.click()
        assert _wait_until(
            lambda i=i: w._history and w._history[-1][0] == f"text{i}")
    assert len(w._history) == 20
    assert w._history[-1] == ("text24", "译:text24")
    w.close()


# ── 语音区 ──────────────────────────────────────────────────────

def test_page_speech_auto_translate(monkeypatch):
    import modules.translator.page as page_mod
    monkeypatch.setattr(
        page_mod, "translate_text",
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "译:" + text)
    w = _make_page()
    check = w.findChild(QtWidgets.QCheckBox)
    assert check is not None
    check.setChecked(True)
    w._on_speech("hello")
    assert _wait_until(lambda: w._label_auto.text() == "译:hello")
    assert w._edit_recog.toPlainText() == "hello"
    w.close()


def test_page_speech_start_stop(monkeypatch):
    import modules.translator.page as page_mod

    class _FakeSignal:
        def connect(self, cb):
            self._cb = cb

    class _FakeRec:
        def __init__(self):
            self.is_listening = False
            self.on_result = _FakeSignal()

        def start(self):
            self.is_listening = True
            return True

        def stop(self):
            self.is_listening = False

    fake = _FakeRec()
    monkeypatch.setattr(page_mod, "SpeechRecognizer", lambda: fake)
    w = _make_page()
    start_btn = [b for b in w.findChildren(QtWidgets.QPushButton)
                 if b.text() == "开始"][0]
    stop_btn = [b for b in w.findChildren(QtWidgets.QPushButton)
                if b.text() == "停止"][0]
    start_btn.click()
    assert fake.is_listening is True
    assert w._label_status.text() == "正在聆听"
    assert stop_btn.isEnabled()
    stop_btn.click()
    assert fake.is_listening is False
    assert w._label_status.text() == "已停止"
    w.close()


# ── 字幕区集成（依赖 subtitle_widget）──────────────────────────

def test_page_subtitle_toggle():
    _app()
    w = _make_page()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "显示悬浮字幕"][0]
    btn.click()
    assert w._subtitle_panel._subtitle is not None
    assert btn.text() == "关闭悬浮字幕"
    w._subtitle_panel._subtitle.set_content("Hello", "你好")
    assert w._subtitle_panel._subtitle._label_trans.text() == "你好"
    btn.click()
    assert w._subtitle_panel._subtitle is None
    assert btn.text() == "显示悬浮字幕"
    w.close()


def test_page_subtitle_receives_speech(monkeypatch):
    import modules.translator.page as page_mod
    monkeypatch.setattr(
        page_mod, "translate_text",
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "译:" + text)
    w = _make_page()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "显示悬浮字幕"][0]
    btn.click()
    check = w.findChild(QtWidgets.QCheckBox)
    check.setChecked(True)
    w._on_speech("hello")
    assert _wait_until(
        lambda: w._subtitle_panel._subtitle._label_trans.text() == "译:hello")
    assert w._subtitle_panel._subtitle._label_orig.text() == "hello"
    w.close()


# ── 异步翻译：工作线程 + 信号回主线程 ─────────────────────────────

def test_page_translate_runs_in_worker_thread(monkeypatch):
    """翻译必须在非主线程执行（Google 5s / LLM 10s 超时不得冻结 UI）。"""
    import threading
    import modules.translator.page as page_mod
    main_tid = threading.get_ident()
    captured = {}

    def recording_translate(text, src_lang="auto", dst_lang="zh-CN", provider="google"):
        captured["tid"] = threading.get_ident()
        return "译:" + text

    monkeypatch.setattr(page_mod, "translate_text", recording_translate)
    w = _make_page()
    edits = _edits(w)
    edits[0].setPlainText("Hello")
    _translate_btn(w).click()
    assert _wait_until(lambda: "tid" in captured), "翻译线程应已执行"
    assert captured["tid"] != main_tid, "translate_text 不得在主线程执行"
    assert _wait_until(lambda: edits[1].toPlainText() == "译:Hello")
    w.close()


def test_page_speech_auto_translate_runs_in_worker_thread(monkeypatch):
    """语音自动翻译同样在非主线程执行。"""
    import threading
    import modules.translator.page as page_mod
    main_tid = threading.get_ident()
    captured = {}

    def recording_translate(text, src_lang="auto", dst_lang="zh-CN", provider="google"):
        captured["tid"] = threading.get_ident()
        return "译:" + text

    monkeypatch.setattr(page_mod, "translate_text", recording_translate)
    w = _make_page()
    check = w.findChild(QtWidgets.QCheckBox)
    check.setChecked(True)
    w._on_speech("hello")
    assert _wait_until(lambda: "tid" in captured), "翻译线程应已执行"
    assert captured["tid"] != main_tid, "translate_text 不得在主线程执行"
    assert _wait_until(lambda: w._label_auto.text() == "译:hello")
    w.close()


def test_page_destroy_while_translate_pending_no_crash(monkeypatch):
    """页面销毁时挂起的翻译线程不得崩溃（信号自动断开 + RuntimeError 兜底）。"""
    import threading
    import time
    import modules.translator.page as page_mod
    started = threading.Event()
    release = threading.Event()

    def slow_translate(text, src_lang="auto", dst_lang="zh-CN", provider="google"):
        started.set()
        release.wait(5)
        return "译:" + text

    monkeypatch.setattr(page_mod, "translate_text", slow_translate)
    w = _make_page()
    edits = _edits(w)
    edits[0].setPlainText("Hello")
    _translate_btn(w).click()
    assert started.wait(2), "翻译线程应已启动"
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    release.set()  # 结果在页面销毁后到达
    for _ in range(20):
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    # 不崩溃即通过


def test_page_translate_stale_result_discarded(monkeypatch):
    """防抖：连续触发翻译时，过期结果不得覆盖最新结果。"""
    import threading
    import time
    import modules.translator.page as page_mod
    release = threading.Event()

    def slow_translate(text, src_lang="auto", dst_lang="zh-CN", provider="google"):
        release.wait(5)
        return "译:" + text

    monkeypatch.setattr(page_mod, "translate_text", slow_translate)
    w = _make_page()
    edits = _edits(w)
    edits[0].setPlainText("first")
    _translate_btn(w).click()
    edits[0].setPlainText("second")
    _translate_btn(w).click()
    release.set()
    assert _wait_until(lambda: edits[1].toPlainText() == "译:second")
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    assert edits[1].toPlainText() == "译:second", "过期结果不得覆盖最新结果"
    w.close()


# ── 子进程冒烟：输入→翻译→显示结果 ─────────────────────────────

def test_page_smoke_no_crash_subprocess():
    import subprocess
    from pathlib import Path
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_translator_page.py::test_page_smoke_no_crash_child", "-q"],
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


def test_page_smoke_no_crash_child():
    """子进程冒烟：输入→翻译→显示结果→关闭。"""
    import time
    import modules.translator.page as page_mod
    page_mod.translate_text = (
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "译:" + text)
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    w = page_mod._make_page_widget(_Owner(), None)
    w.resize(1000, 700)
    w.show()
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
    edits = w.findChildren(QtWidgets.QPlainTextEdit)
    edits[0].setPlainText("Hello")
    btn = [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "翻译"][0]
    btn.click()
    deadline = time.time() + 3
    while time.time() < deadline and edits[1].toPlainText() != "译:Hello":
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)
    assert edits[1].toPlainText() == "译:Hello"
    w.close()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    print("TRANSLATOR_PAGE_SMOKE_OK")