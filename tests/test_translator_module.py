"""translator 模块骨架与首页卡片测试。"""
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


# ── 模块骨架 ─────────────────────────────────────────────────────

def test_module_info():
    from modules.translator import MODULE_INFO
    assert MODULE_INFO["id"] == "translator"
    assert MODULE_INFO["name"] == "翻译工具"
    assert MODULE_INFO["description"] == "在线翻译与语音识别实时翻译"


def test_module_builds():
    _app()
    from modules.translator.module import Module
    mod = Module(_Owner())
    assert mod.MODULE_ID == "translator"
    assert mod.MODULE_NAME == "翻译工具"
    assert mod.ENABLED_BY_DEFAULT is True
    assert mod.id == "translator"
    assert mod.name == "翻译工具"


def test_module_create_home_widget():
    _app()
    from modules.translator.module import Module
    mod = Module(_Owner())
    w = mod.create_home_widget(None)
    assert w is not None
    w.close()


def test_registry_discovers_translator():
    _app()
    from core.config import AppConfig
    from modules.registry import ModuleContext, ModuleRegistry
    config = AppConfig()
    context = ModuleContext(config=config, host_window=None, app=_app())
    reg = ModuleRegistry(context)
    ids = [m.id for m in reg.all()]
    assert "translator" in ids, f"translator 应被注册，实际: {ids}"
    assert reg.is_enabled("translator") is True


# ── 首页卡片 ─────────────────────────────────────────────────────

def _make_home():
    _app()
    from modules.translator.home import _make_home_widget
    w = _make_home_widget(_Owner(), None)
    w.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    return w


def test_home_widget_has_translate_input():
    w = _make_home()
    edits = w.findChildren(QtWidgets.QPlainTextEdit)
    assert len(edits) == 2  # 输入 + 只读结果
    assert edits[1].isReadOnly()
    combos = w.findChildren(ComboBox)
    assert len(combos) == 3  # 源语言 / 目标语言 / provider
    buttons = [b.text() for b in w.findChildren(QtWidgets.QPushButton)]
    assert "翻译" in buttons
    assert "开始语音识别" in buttons
    w.close()


def test_home_translate_flow(monkeypatch):
    import modules.translator.home as home_mod
    monkeypatch.setattr(
        home_mod, "translate_text",
        lambda text, src_lang="auto", dst_lang="zh-CN", provider="google": "你好")
    w = _make_home()
    edits = w.findChildren(QtWidgets.QPlainTextEdit)
    edits[0].setPlainText("Hello")
    btn = [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "翻译"][0]
    btn.click()
    QtWidgets.QApplication.processEvents()
    assert edits[1].toPlainText() == "你好"
    w.close()


def test_home_translate_empty_input_no_crash(monkeypatch):
    import modules.translator.home as home_mod
    monkeypatch.setattr(home_mod, "translate_text", lambda *a, **k: "X")
    w = _make_home()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton) if b.text() == "翻译"][0]
    btn.click()  # 空输入：不应调用翻译
    assert w._edit_result.toPlainText() == ""
    w.close()


def test_home_open_page_link(monkeypatch):
    from modules.translator.home import _make_home_widget
    opened = []
    monkeypatch.setattr(
        "ui.module_pages.open_module_page", lambda mod, parent: opened.append(mod))
    w = _make_home()
    link = [l for l in w.findChildren(QtWidgets.QLabel)
            if "打开完整页面" in l.text()][0]
    link.linkActivated.emit("")
    assert len(opened) == 1
    w.close()


class _FakeSignal:
    def connect(self, cb):
        self._cb = cb

    def emit(self, *args):
        if getattr(self, "_cb", None):
            self._cb(*args)


class _FakeRec:
    def __init__(self):
        self.is_listening = False
        self.on_result = _FakeSignal()

    def start(self):
        self.is_listening = True
        return True

    def stop(self):
        self.is_listening = False


def test_home_speech_toggle(monkeypatch):
    from modules.translator.home import _make_home_widget
    fake = _FakeRec()
    monkeypatch.setattr(
        "modules.translator.speech_core.SpeechRecognizer", lambda: fake)
    w = _make_home()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "开始语音识别"][0]
    btn.click()
    assert fake.is_listening is True
    assert btn.text() == "停止语音识别"
    btn.click()
    assert fake.is_listening is False
    assert btn.text() == "开始语音识别"
    w.close()


def test_home_speech_unavailable(monkeypatch):
    from modules.translator.home import _make_home_widget

    class _NoMicRec(_FakeRec):
        def start(self):
            return False

    fake = _NoMicRec()
    monkeypatch.setattr(
        "modules.translator.speech_core.SpeechRecognizer", lambda: fake)
    w = _make_home()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "开始语音识别"][0]
    btn.click()
    assert w._label_speech.text() == "语音识别不可用"
    assert btn.text() == "开始语音识别"
    w.close()


def test_home_speech_result_shown(monkeypatch):
    from modules.translator.home import _make_home_widget
    fake = _FakeRec()
    monkeypatch.setattr(
        "modules.translator.speech_core.SpeechRecognizer", lambda: fake)
    w = _make_home()
    btn = [b for b in w.findChildren(QtWidgets.QPushButton)
           if b.text() == "开始语音识别"][0]
    btn.click()
    fake.on_result.emit("你好世界")
    assert w._label_speech.text() == "你好世界"
    assert w._edit_src.toPlainText() == "你好世界"
    w.close()


def test_home_provider_dropdown(monkeypatch):
    import modules.translator.home as home_mod
    saved = []
    monkeypatch.setattr(home_mod, "get_provider", lambda: "google")
    monkeypatch.setattr(home_mod, "set_provider", lambda v: saved.append(v))
    w = _make_home()
    combos = w.findChildren(ComboBox)
    prov = combos[2]
    assert prov.itemData(1) == "llm"
    prov.setCurrentIndex(1)
    assert saved == ["llm"]
    w.close()