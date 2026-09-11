"""speech_core 测试：构建、状态切换、信号、失败路径（不依赖真实麦克风）。"""
import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.translator.speech_core import SpeechRecognizer


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def test_construct_no_error():
    _app()
    rec = SpeechRecognizer()
    assert rec.is_listening is False
    assert rec.language == "zh-CN"


def test_set_language_stores():
    rec = SpeechRecognizer()
    rec.set_language("en-US")
    assert rec.language == "en-US"


def test_start_stop_state_transition(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    monkeypatch.setattr(rec, "_start_comtypes", lambda: False)
    monkeypatch.setattr(rec, "_start_powershell", lambda: True)
    assert rec.start() is True
    assert rec.is_listening is True
    rec.stop()
    assert rec.is_listening is False


def test_start_returns_false_when_unavailable(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    monkeypatch.setattr(rec, "_start_comtypes", lambda: False)
    monkeypatch.setattr(rec, "_start_powershell", lambda: False)
    assert rec.start() is False
    assert rec.is_listening is False


def test_stop_idempotent(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    monkeypatch.setattr(rec, "_start_comtypes", lambda: False)
    monkeypatch.setattr(rec, "_start_powershell", lambda: True)
    rec.start()
    rec.stop()
    rec.stop()  # 幂等：不应抛异常
    assert rec.is_listening is False


def test_start_when_already_listening(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    monkeypatch.setattr(rec, "_start_comtypes", lambda: False)
    monkeypatch.setattr(rec, "_start_powershell", lambda: True)
    rec.start()
    assert rec.start() is True
    rec.stop()


def test_comtypes_missing_falls_back_to_powershell(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    calls = []
    monkeypatch.setattr(
        rec, "_start_comtypes", lambda: (calls.append("comtypes"), False)[1])
    monkeypatch.setattr(
        rec, "_start_powershell", lambda: (calls.append("ps"), True)[1])
    assert rec.start() is True
    assert calls == ["comtypes", "ps"]
    rec.stop()


def test_start_powershell_popen_failure(monkeypatch):
    _app()
    rec = SpeechRecognizer()
    monkeypatch.setattr(rec, "_start_comtypes", lambda: False)

    def _boom(*_a, **_k):
        raise OSError("no powershell")

    monkeypatch.setattr(
        "modules.translator.speech_core.subprocess.Popen", _boom)
    assert rec.start() is False
    assert rec.is_listening is False


def test_on_result_signal_emits():
    _app()
    rec = SpeechRecognizer()
    got = []
    rec.on_result.connect(lambda t: got.append(t))
    rec.on_result.emit("你好")
    assert got == ["你好"]


def test_read_loop_emits_lines():
    _app()
    rec = SpeechRecognizer()

    class _FakeStream:
        def __iter__(self):
            yield b"hello\n"
            yield b"world\n"

    class _FakeProc:
        stdout = _FakeStream()

    rec._proc = _FakeProc()
    got = []
    rec.on_result.connect(lambda t: got.append(t))
    rec._read_loop()
    assert got == ["hello", "world"]


def test_read_loop_stops_when_flag_set():
    _app()
    rec = SpeechRecognizer()

    class _FakeStream:
        def __iter__(self):
            yield b"hello\n"
            yield b"world\n"

    class _FakeProc:
        stdout = _FakeStream()

    rec._proc = _FakeProc()
    rec._stop_flag.set()
    got = []
    rec.on_result.connect(lambda t: got.append(t))
    rec._read_loop()
    assert got == []