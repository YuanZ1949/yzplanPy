"""RecordingSession / 脱敏 / 环境开关 单测。纯数据 + 一个 Qt 线程接线测试（用 qapp fixture）。"""
import json

from modules.router_admin import recorder, replay
from modules.router_admin.recorder import RecordingSession, wrap_if_recording
from modules.router_admin.replay import ReplaySession, redact


class _Inner:
    """最小内层会话：run 回固定映射，run_batch 逐条。"""

    def __init__(self, replies):
        self.replies = replies
        self.opened = False
        self.closed = False
        self.calls = []

    @property
    def connected(self):
        return self.opened and not self.closed

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def run(self, command, *, timeout=None):
        self.calls.append(command)
        return self.replies.get(command, "")

    def run_batch(self, commands, *, timeout=None):
        return [self.run(c) for c in (commands or [])]


def test_记录send与recv序列(tmp_path):
    path = tmp_path / "rec.json"
    inner = _Inner({"uptime": "UP 1 day"})
    s = RecordingSession(inner, str(path), device="d")
    s.open()
    assert s.run("uptime") == "UP 1 day"          # 真实输出原样返回，不被脱敏
    s.close()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["steps"] == [{"kind": "command", "send": "uptime", "recv": "UP 1 day"}]


def test_口令在send与recv里都被脱敏(tmp_path):
    path = tmp_path / "rec.json"
    inner = _Inner({"uci set x='s3cr3t'": "echo uci set x='s3cr3t'"})
    s = RecordingSession(inner, str(path), secrets=["s3cr3t"])
    s.open()
    s.run("uci set x='s3cr3t'")
    s.close()
    raw = path.read_text(encoding="utf-8")
    assert "s3cr3t" not in raw
    assert raw.count("***") == 2


def test_落盘后可被ReplaySession回放(tmp_path):
    path = tmp_path / "rec.json"
    s = RecordingSession(_Inner({"a": "A", "b": "B"}), str(path))
    s.open()
    s.run("a")
    s.run("b")
    s.close()
    r = ReplaySession.from_file(str(path))
    r.open()
    assert r.run("a") == "A" and r.run("b") == "B"


def test_flush幂等(tmp_path):
    path = tmp_path / "rec.json"
    s = RecordingSession(_Inner({"a": "A"}), str(path))
    s.open()
    s.run("a")
    s.flush()
    s.flush()
    assert json.loads(path.read_text(encoding="utf-8"))["steps"] == [
        {"kind": "command", "send": "a", "recv": "A"}]


def test_落盘失败不抛出(tmp_path, monkeypatch):
    """录制开关开着但路径不可写：绝不能把真实任务弄挂。"""
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(replay.json, "dump", boom)
    s = RecordingSession(_Inner({"a": "A"}), str(tmp_path / "rec.json"))
    s.open()
    assert s.run("a") == "A"
    s.close()                                     # 不得抛异常


def test_wrap_if_recording_未设环境变量_原样返回():
    inner = _Inner({})
    assert wrap_if_recording(inner, environ={}) is inner


def test_wrap_if_recording_设了环境变量_包一层(tmp_path):
    inner = _Inner({})
    env = {recorder.ENV_RECORD_PATH: str(tmp_path / "rec.json"),
           recorder.ENV_RECORD_DEVICE: "router-x"}
    wrapped = wrap_if_recording(inner, secrets=["p"], environ=env)
    assert isinstance(wrapped, RecordingSession)


def test_redact_只替换非空密钥():
    assert redact("a secret b", ["secret", ""]) == "a *** b"
    assert redact("", ["x"]) == ""


# --- 以下为 brief 用例之外补的：覆盖 run_batch 记录、元数据落盘、状态透传、
#     以及「先 flush 再产生新步骤」不能丢步骤（flush 的幂等语义边界）。 ---


def test_run_batch_逐条记录且返回未脱敏真值(tmp_path):
    path = tmp_path / "rec.json"
    inner = _Inner({"a": "A-pw", "b": "B"})
    s = RecordingSession(inner, str(path), secrets=["pw"])
    s.open()
    got = s.run_batch(["a", "b"])
    s.close()
    assert got == ["A-pw", "B"]                   # 真实任务拿到的仍是真值
    assert json.loads(path.read_text(encoding="utf-8"))["steps"] == [
        {"kind": "command", "send": "a", "recv": "A-***"},
        {"kind": "command", "send": "b", "recv": "B"}]


def test_落盘含版本与元数据_并自动建目录(tmp_path):
    path = tmp_path / "nested" / "dir" / "rec.json"    # 目录不存在也要能落盘
    s = RecordingSession(_Inner({}), str(path), device="router-x", firmware="1.2.3",
                        captured_at="2026-10-07T10:00:00")
    s.close()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == replay.RECORD_FORMAT_VERSION
    assert (data["device"], data["firmware"], data["captured_at"]) == (
        "router-x", "1.2.3", "2026-10-07T10:00:00")
    assert data["steps"] == []


def test_connected透传内层状态(tmp_path):
    inner = _Inner({})
    s = RecordingSession(inner, str(tmp_path / "rec.json"))
    assert s.connected is False
    s.open()
    assert s.connected is True
    s.close()
    assert s.connected is False
    assert inner.closed is True                   # close 先落盘、再关内层


def test_flush后再有新步骤_关闭时补写(tmp_path):
    """flush 只在「无新步骤」时短路；之后又跑了命令，收尾 flush 必须补写。"""
    path = tmp_path / "rec.json"
    s = RecordingSession(_Inner({"a": "A", "b": "B"}), str(path))
    s.open()
    s.run("a")
    s.flush()
    s.run("b")
    s.close()
    steps = json.loads(path.read_text(encoding="utf-8"))["steps"]
    assert [step["send"] for step in steps] == ["a", "b"]


# --- RouterTask 接线：录制开关必须能挂到真实后台任务上，且默认关闭时零影响。 ---


class _StubTelnetSession:
    """顶替 TelnetSession 的最小桩：只留下构造参数，供接线断言。"""

    def __init__(self, *a, **k):
        self.args = a

    def open(self):
        pass

    def close(self):
        pass

    def run(self, command, *, timeout=None):
        return f"echo {command}"

    @property
    def connected(self):
        return True


def test_RouterTask_make_session_按环境变量包录制(qapp, monkeypatch, tmp_path):
    from modules.router_admin import workers
    from modules.router_admin.connection import ConnectionParams

    path = tmp_path / "rec.json"
    monkeypatch.setattr(workers, "TelnetSession", _StubTelnetSession)
    monkeypatch.setenv(recorder.ENV_RECORD_PATH, str(path))
    monkeypatch.setenv(recorder.ENV_RECORD_DEVICE, "router-x")
    params = ConnectionParams(password="s3cr3t")

    session = workers.RouterTask(params, lambda s: None, label="t")._make_session()

    assert isinstance(session, RecordingSession)
    assert isinstance(session._inner, _StubTelnetSession)
    # 构造参数原样传给内层（抽方法不得改接线参数）
    assert session._inner.args == (params.host, params.port, params.user,
                                   params.password, params.connect_timeout,
                                   params.read_timeout)
    session.open()
    session.run(f"uci set pw='{params.password}'")
    session.close()
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw)["device"] == "router-x"      # 设备名取环境变量
    assert "s3cr3t" not in raw                          # 口令脱敏后才落盘


def test_RouterTask_make_session_未设环境变量_返回真实会话(qapp, monkeypatch):
    from modules.router_admin import workers
    from modules.router_admin.connection import ConnectionParams

    monkeypatch.setattr(workers, "TelnetSession", _StubTelnetSession)
    monkeypatch.delenv(recorder.ENV_RECORD_PATH, raising=False)

    session = workers.RouterTask(ConnectionParams(), lambda s: None)._make_session()

    assert isinstance(session, _StubTelnetSession)
