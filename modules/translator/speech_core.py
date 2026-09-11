"""语音识别核心：Windows SAPI 语音转文字。

优先使用 comtypes 调用 SAPI COM（SAPI.SpSharedRecognizer）；comtypes 不可用时
回退到 PowerShell System.Speech.Recognition 子进程。两条路径均不阻塞 UI 线程。
"""
import subprocess
import threading
import time

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

# PowerShell 回退脚本：System.Speech.Recognition 引擎，识别结果逐行输出到 stdout。
# 语言参数经 $args[0] 传入；指定语言不可用时自动回退到系统默认语言。
_PS_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$lang = $args[0]
$rec = $null
if ($lang) {
    try {
        $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($lang)
    } catch {
        $rec = $null
    }
}
if (-not $rec) {
    $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine
}
$rec.SetInputToDefaultAudioDevice()
$grammar = New-Object System.Speech.Recognition.DictationGrammar
$rec.LoadGrammar($grammar)
$handler = [System.Speech.Recognition.SpeechRecognizedEventHandler]{
    param($sender, $e)
    if ($e.Result -and $e.Result.Text) {
        [Console]::Out.WriteLine($e.Result.Text)
        [Console]::Out.Flush()
    }
}
$rec.AddHandler([System.Speech.Recognition.SpeechRecognitionEngine]::Recognized, $handler)
$rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
while ($true) { Start-Sleep -Milliseconds 200 }
"""

# SAPI 语言 → LCID（十六进制字符串），用于 comtypes 路径设置识别语言
_SAPI_LCID = {
    "zh-CN": "804",
    "en-US": "409",
    "ja-JP": "411",
    "ko-KR": "412",
    "fr-FR": "40C",
    "de-DE": "407",
    "es-ES": "40A",
}


def _import_comtypes():
    """comtypes 可选依赖：未安装返回 None（走 PowerShell 回退路径）。"""
    import importlib
    try:
        return importlib.import_module("comtypes.client")
    except ImportError:
        return None


class _SapiEvents:
    """comtypes SAPI 事件接收器（仅 comtypes 路径使用）。"""

    def __init__(self, owner):
        self._owner = owner

    def OnRecognition(self, stream_number, stream_position, recognition_type, result):
        try:
            text = result.PhraseInfo.GetText()
        except Exception:
            return
        if text:
            self._owner.on_result.emit(text)


class SpeechRecognizer(QtCore.QObject):
    """Windows SAPI 语音识别器：start/stop 状态机 + on_result 信号。"""

    on_result = QtCore.Signal(str)

    def __init__(self, language="zh-CN"):
        super().__init__()
        self._language = language
        self._listening = False
        self._proc = None
        self._thread = None
        self._stop_flag = threading.Event()
        self._com = None
        self._sink = None

    @property
    def is_listening(self):
        return self._listening

    @property
    def language(self):
        return self._language

    def set_language(self, language):
        """设置识别语言；已启动的 comtypes 识别器会尝试即时应用。"""
        self._language = language
        if self._com is not None:
            try:
                self._com.Recognizer.SetProperty(
                    "SRATopLevel", _SAPI_LCID.get(language, "804"))
            except Exception:
                pass

    def start(self):
        """开始监听。成功返回 True；麦克风/COM 不可用返回 False（绝不抛出）。"""
        if self._listening:
            return True
        if self._start_comtypes():
            self._listening = True
            return True
        if self._start_powershell():
            self._listening = True
            return True
        return False

    def stop(self):
        """停止监听。幂等。"""
        if not self._listening:
            return
        self._listening = False
        self._stop_flag.set()
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None
        if self._com is not None:
            self._com = None
            self._sink = None
        self._thread = None

    def _start_comtypes(self):
        """comtypes SAPI 路径；comtypes 未安装或初始化失败返回 False。"""
        client = _import_comtypes()
        if client is None:
            return False
        try:
            rec = client.CreateObject("SAPI.SpSharedRecognizer")
            sink = _SapiEvents(self)
            client.GetEvents(rec, sink)
            self._com = rec
            self._sink = sink
            return True
        except Exception:
            self._com = None
            self._sink = None
            return False

    def _start_powershell(self):
        """PowerShell System.Speech 子进程路径。"""
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 _PS_SCRIPT, self._language],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except Exception:
            return False
        # 等待进程存活确认：引擎初始化失败（如无麦克风）会快速退出
        for _ in range(6):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is not None:
            try:
                proc.kill()
            except Exception:
                pass
            return False
        self._proc = proc
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def _read_loop(self):
        """后台线程：逐行读取子进程 stdout，识别结果经信号转发（跨线程安全）。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self._stop_flag.is_set():
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self.on_result.emit(text)
        except Exception:
            pass