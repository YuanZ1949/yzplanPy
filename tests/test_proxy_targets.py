"""proxy_ctrl/targets 单测：七类目标的读 / 设 / 清契约。

Git 用假 runner，Docker 用 tmp_path 下的假 daemon.json，环境变量目标用
FakeBackend —— 全部不触碰真实注册表 / 真实 Git / 真实 Docker。
"""
import json
import os

import pytest

from modules.proxy_ctrl import envstore, target_docker, targets
from modules.proxy_ctrl.targets import (CompositeTarget, DockerTarget, EnvTarget,
                                        GitTarget, TargetResult)


class FakeBackend(envstore.RegistryBackend):
    """内存注册表后端（与 test_proxy_envstore 中的同名类等价，此处独立定义）。"""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.calls = []

    def get(self, name):
        self.calls.append(("get", name))
        return self.data.get(name)

    def set(self, name, value):
        self.calls.append(("set", name, value))
        self.data[name] = str(value)

    def delete(self, name):
        self.calls.append(("delete", name))
        self.data.pop(name, None)


@pytest.fixture(autouse=True)
def _no_broadcast(monkeypatch):
    """禁掉真实 WM_SETTINGCHANGE 广播。"""
    monkeypatch.setattr(envstore, "_broadcast_impl", lambda timeout_ms: False)


@pytest.fixture
def _restore_environ():
    keys = ("http_proxy", "https_proxy", "socks_proxy",
            "WGET_PROXY", "HTTP_PROXY", "HTTPS_PROXY")
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ── GitTarget ─────────────────────────────────────────────────────────

def _git_ok(*results):
    """构造一个按调用顺序返回结果的假 git runner。"""
    queue = list(results)

    def _run(args):
        if not queue:
            return 0, "", ""
        return queue.pop(0)

    return _run


def test_git_read_returns_http_proxy_first():
    run = _git_ok((0, "http://127.0.0.1:7890", ""))
    target = GitTarget(runner=run, which=lambda _n: "C:/git.exe")
    assert target.read() == "http://127.0.0.1:7890"


def test_git_read_falls_back_to_https_proxy():
    run = _git_ok((1, "", ""), (0, "http://127.0.0.1:1080", ""))
    target = GitTarget(runner=run, which=lambda _n: "C:/git.exe")
    assert target.read() == "http://127.0.0.1:1080"


def test_git_read_returns_none_when_unset():
    run = _git_ok((1, "", ""), (1, "", ""))
    target = GitTarget(runner=run, which=lambda _n: "C:/git.exe")
    assert target.read() is None


def test_git_read_returns_none_when_git_missing():
    target = GitTarget(runner=lambda a: (0, "x", ""), which=lambda _n: None)
    assert target.read() is None


def test_git_set_writes_both_keys():
    seen = []

    def _run(args):
        seen.append(args)
        return 0, "", ""

    target = GitTarget(runner=_run, which=lambda _n: "C:/git.exe")
    result = target.set("http://127.0.0.1:7890")
    assert result.ok
    assert seen == [
        ["config", "--global", "http.proxy", "http://127.0.0.1:7890"],
        ["config", "--global", "https.proxy", "http://127.0.0.1:7890"],
    ]


def test_git_set_reports_failure_detail():
    target = GitTarget(runner=lambda a: (1, "", "bad config"),
                       which=lambda _n: "C:/git.exe")
    result = target.set("http://x:1")
    assert result.ok is False
    assert "http.proxy" in result.detail


def test_git_set_skipped_when_git_missing():
    target = GitTarget(runner=lambda a: (0, "", ""), which=lambda _n: None)
    result = target.set("http://127.0.0.1:7890")
    assert result.ok is False
    assert "Git" in result.message


def test_git_unset_uses_unset_verb():
    seen = []
    target = GitTarget(runner=lambda a: seen.append(a) or (5, "", "not found"),
                       which=lambda _n: "C:/git.exe")
    result = target.unset()
    assert result.ok  # --unset 对不存在的键返回非 0，不算失败
    assert seen == [
        ["config", "--global", "--unset", "http.proxy"],
        ["config", "--global", "--unset", "https.proxy"],
    ]


def test_git_unset_skipped_when_git_missing():
    target = GitTarget(runner=lambda a: (0, "", ""), which=lambda _n: None)
    assert target.unset().ok is False


# ── EnvTarget ─────────────────────────────────────────────────────────

def test_env_read_returns_first_non_empty_key():
    backend = FakeBackend({"https_proxy": "http://127.0.0.1:7890"})
    target = EnvTarget("curl", "cURL", targets.CURL_KEYS, backend)
    assert target.read() == "http://127.0.0.1:7890"


def test_env_read_returns_none_when_all_empty():
    backend = FakeBackend({"http_proxy": "", "https_proxy": "   "})
    target = EnvTarget("curl", "cURL", targets.CURL_KEYS, backend)
    assert target.read() is None


def test_env_set_writes_every_key(_restore_environ):
    backend = FakeBackend()
    target = EnvTarget("node", "Node.js", targets.NODE_KEYS, backend)
    result = target.set("http://127.0.0.1:7890")
    assert result.ok
    assert backend.data == {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "HTTPS_PROXY": "http://127.0.0.1:7890",
    }


def test_env_set_reports_backend_failure(_restore_environ):
    class Broken(FakeBackend):
        def set(self, name, value):
            raise OSError("registry denied")

    target = EnvTarget("node", "Node.js", targets.NODE_KEYS, Broken())
    result = target.set("http://x:1")
    assert result.ok is False
    assert "denied" in result.detail


def test_env_unset_deletes_every_key(_restore_environ):
    backend = FakeBackend({"WGET_PROXY": "http://x:1"})
    target = EnvTarget("wget", "wget", targets.WGET_KEYS, backend)
    assert target.unset().ok
    assert backend.data == {}


def test_env_unset_reports_backend_failure(_restore_environ):
    class Broken(FakeBackend):
        def delete(self, name):
            raise OSError("locked")

    target = EnvTarget("wget", "wget", targets.WGET_KEYS, Broken())
    result = target.unset()
    assert result.ok is False
    assert "locked" in result.detail


# ── CompositeTarget ───────────────────────────────────────────────────

def test_composite_read_returns_first_child_with_value(_restore_environ):
    a = EnvTarget("a", "A", ("A_KEY",), FakeBackend())
    b = EnvTarget("b", "B", ("B_KEY",), FakeBackend({"B_KEY": "http://b:2"}))
    assert CompositeTarget("g", "全局", [a, b]).read() == "http://b:2"


def test_composite_read_returns_none_when_all_empty(_restore_environ):
    a = EnvTarget("a", "A", ("A_KEY",), FakeBackend())
    b = EnvTarget("b", "B", ("B_KEY",), FakeBackend())
    assert CompositeTarget("g", "全局", [a, b]).read() is None


def test_composite_set_propagates_to_all_children(_restore_environ):
    a = EnvTarget("a", "A", ("A_KEY",), FakeBackend())
    b = EnvTarget("b", "B", ("B_KEY",), FakeBackend())
    result = CompositeTarget("g", "全局", [a, b]).set("http://x:1")
    assert result.ok
    assert a.read() == "http://x:1" and b.read() == "http://x:1"


def test_composite_set_succeeds_with_partial_failure(_restore_environ):
    class Broken(EnvTarget):
        def set(self, url):
            return TargetResult(False, "boom", "detail")

    a = EnvTarget("a", "A", ("A_KEY",), FakeBackend())
    b = Broken("b", "B", ("B_KEY",), FakeBackend())
    result = CompositeTarget("g", "全局", [a, b]).set("http://x:1")
    assert result.ok
    assert "1/2" in result.message


def test_composite_set_fails_when_all_children_fail(_restore_environ):
    class Broken(EnvTarget):
        def set(self, url):
            return TargetResult(False, "boom", "detail")

    children = [Broken("a", "A", ("A_KEY",), FakeBackend()),
                Broken("b", "B", ("B_KEY",), FakeBackend())]
    result = CompositeTarget("g", "全局", children).set("http://x:1")
    assert result.ok is False


# ── DockerTarget ──────────────────────────────────────────────────────

def _write_daemon(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _read_daemon(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_docker_read_returns_http_proxy(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"proxies": {"http-proxy": "http://127.0.0.1:7890"}})
    assert DockerTarget([str(path)]).read() == "http://127.0.0.1:7890"


def test_docker_read_returns_none_without_proxies_node(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"registry-mirrors": []})
    assert DockerTarget([str(path)]).read() is None


def test_docker_read_skips_unparseable_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    good = tmp_path / "daemon.json"
    _write_daemon(good, {"proxies": {"http-proxy": "http://ok:1"}})
    assert DockerTarget([str(bad), str(good)]).read() == "http://ok:1"


def test_docker_set_creates_proxies_node_preserving_other_keys(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"log-level": "debug"})
    result = DockerTarget([str(path)]).set("http://127.0.0.1:7890")
    assert result.ok
    data = _read_daemon(path)
    assert data["log-level"] == "debug"
    assert data["proxies"]["http-proxy"] == "http://127.0.0.1:7890"
    assert data["proxies"]["https-proxy"] == "http://127.0.0.1:7890"


def test_docker_set_writes_utf8_without_bom(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {})
    DockerTarget([str(path)]).set("http://x:1")
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_docker_set_skips_missing_files(tmp_path):
    result = DockerTarget([str(tmp_path / "nope.json")]).set("http://x:1")
    assert result.ok is False
    assert "未找到" in result.message


def test_docker_set_does_not_create_missing_file(tmp_path):
    path = tmp_path / "nope.json"
    DockerTarget([str(path)]).set("http://x:1")
    assert not path.exists()


def test_docker_set_reports_all_unparseable(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    result = DockerTarget([str(path)]).set("http://x:1")
    assert result.ok is False
    assert "无法解析" in result.detail


def test_docker_unset_removes_proxies_node(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"log-level": "info", "proxies": {"http-proxy": "http://x:1"}})
    result = DockerTarget([str(path)]).unset()
    assert result.ok
    assert _read_daemon(path) == {"log-level": "info"}


def test_docker_unset_is_noop_when_no_proxies_node(tmp_path):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"log-level": "info"})
    assert DockerTarget([str(path)]).unset().ok
    assert _read_daemon(path) == {"log-level": "info"}


def test_docker_unset_reports_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "daemon.json"
    _write_daemon(path, {"proxies": {"http-proxy": "http://x:1"}})
    # _write_json 已随 Docker 分支原子切到 target_docker；打桩要打在
    # 实现所在模块上，否则打在被 re-export 的名字上不生效。
    monkeypatch.setattr(target_docker, "_write_json",
                        lambda p, d: "Permission denied")
    result = DockerTarget([str(path)]).unset()
    assert result.ok is False
    assert "管理员" in result.message


# ── all_targets ───────────────────────────────────────────────────────

def test_all_targets_returns_seven_targets_in_order():
    got = targets.all_targets(backend=FakeBackend())
    assert [t.id for t in got] == [
        "git", "curl", "wget", "python", "node", "global", "docker"]


def test_all_targets_global_is_composite():
    got = {t.id: t for t in targets.all_targets(backend=FakeBackend())}
    assert isinstance(got["global"], CompositeTarget)
    assert isinstance(got["docker"], DockerTarget)


def test_all_targets_every_target_has_note():
    for target in targets.all_targets(backend=FakeBackend()):
        assert target.name
        assert target.note
