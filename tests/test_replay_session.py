"""ReplaySession 单测：按序回放、失配/用尽即 AssertionError、格式校验。纯数据，无 Qt。"""
import json

import pytest

from modules.router_admin.replay import (RECORD_FORMAT_VERSION, ReplaySession,
                                         load_recording)

STEPS = [
    {"send": "cat /etc/config/network 2>/dev/null", "recv": "config interface 'wan'\n"},
    {"send": "uptime", "recv": " 12:00 up 1 day"},
]


def _write(tmp_path, payload):
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _session(**kw):
    s = ReplaySession(list(STEPS), **kw)
    s.open()
    return s


def test_按序回放_返回录制输出并推进():
    s = _session()
    assert s.run("cat /etc/config/network 2>/dev/null").startswith("config interface")
    assert s.consumed == 1 and s.remaining == 1
    assert s.run("uptime") == " 12:00 up 1 day"
    assert s.remaining == 0


def test_命令与录制不匹配_抛AssertionError且不前进():
    s = _session()
    with pytest.raises(AssertionError) as ei:
        s.run("rm -rf /")
    assert "rm -rf /" in str(ei.value)
    assert s.consumed == 0                      # 失配不消费


def test_序列用尽_抛AssertionError():
    s = _session()
    s.run("cat /etc/config/network 2>/dev/null")
    s.run("uptime")
    with pytest.raises(AssertionError):
        s.run("uptime")


def test_未open时run_抛AssertionError():
    s = ReplaySession(list(STEPS))
    assert s.connected is False
    with pytest.raises(AssertionError):
        s.run("uptime")


def test_open重置进度可重复回放():
    s = _session()
    s.run("cat /etc/config/network 2>/dev/null")
    s.close()
    s.open()
    assert s.consumed == 0
    assert s.run("cat /etc/config/network 2>/dev/null").startswith("config interface")


def test_run_batch_按序消费():
    s = _session()
    got = s.run_batch(["cat /etc/config/network 2>/dev/null", "uptime"])
    assert len(got) == 2 and s.remaining == 0


def test_脱敏通配_任意口令都能匹配但其它改动失配():
    steps = [{"send": "uci set network.wan.password='***'", "recv": ""}]
    s = ReplaySession(steps)
    s.open()
    assert s.run("uci set network.wan.password='real-secret'") == ""
    s.open()
    with pytest.raises(AssertionError):
        s.run("uci set network.wan.username='x'")


def test_from_file_读取夹具(tmp_path):
    path = _write(tmp_path, {"device": "d", "firmware": "f", "captured_at": "2026-10-07",
                             "steps": STEPS})
    s = ReplaySession.from_file(path)
    s.open()
    assert s.run("cat /etc/config/network 2>/dev/null").startswith("config interface")


# --- load_recording 的格式校验（录制文件是外部输入，必须挡在解析层之外） ---


@pytest.mark.parametrize("payload", [
    [],                                                   # 非 dict
    {"steps": "not-a-list"},                              # steps 非 list
    {"steps": ["plain-string"]},                          # 步骤非 dict
    {"steps": [{"send": "uptime"}]},                      # 缺 recv
    {"steps": [{"recv": "ok"}]},                          # 缺 send
    {"steps": [{"send": 1, "recv": "ok"}]},               # send 非 str
    {"steps": [{"send": "uptime", "recv": None}]},         # recv 非 str
])
def test_load_recording_结构非法_抛ValueError(tmp_path, payload):
    path = _write(tmp_path, payload)
    with pytest.raises(ValueError):
        load_recording(path)


def test_load_recording_缺失元数据_回填空串(tmp_path):
    path = _write(tmp_path, {"steps": STEPS})
    rec = load_recording(path)
    assert rec["device"] == "" and rec["firmware"] == "" and rec["captured_at"] == ""
    assert rec["steps"][0]["send"] == "cat /etc/config/network 2>/dev/null"


# --- 格式版本：RECORD_FORMAT_VERSION 的注释承诺「结构不兼容变更时递增并让旧文件
#     显式失败」，缺了 version 字段会让这个承诺落空。 ---


def test_load_recording_缺version_按当前版本兜底(tmp_path):
    """版本字段缺失不拒绝：首个版本发布前的录制文件没有它，仍要能回放。"""
    path = _write(tmp_path, {"steps": STEPS})
    assert load_recording(path)["version"] == RECORD_FORMAT_VERSION


def test_load_recording_版本一致_正常加载(tmp_path):
    path = _write(tmp_path, {"version": RECORD_FORMAT_VERSION, "steps": STEPS})
    assert load_recording(path)["version"] == RECORD_FORMAT_VERSION


@pytest.mark.parametrize("version", [0, 3, 99, "1", None, True])
def test_load_recording_版本失配_抛ValueError(tmp_path, version):
    path = _write(tmp_path, {"version": version, "steps": STEPS})
    with pytest.raises(ValueError) as ei:
        load_recording(path)
    message = str(ei.value)
    assert str(version) in message and str(RECORD_FORMAT_VERSION) in message


@pytest.mark.parametrize("version", [1, RECORD_FORMAT_VERSION])
def test_load_recording_受支持版本_均接受并归一(tmp_path, version):
    path = _write(tmp_path, {"version": version, "steps": STEPS})
    assert load_recording(path)["version"] == RECORD_FORMAT_VERSION


# --- 步类型 kind（v2 新增；v1 无 kind，按 command 兜底） ---


def test_load_recording_缺kind_默认command(tmp_path):
    path = _write(tmp_path, {"steps": STEPS})
    assert [s["kind"] for s in load_recording(path)["steps"]] == ["command", "command"]


def test_load_recording_保留kind(tmp_path):
    path = _write(tmp_path, {
        "steps": [{"kind": "login_ok", "send": "", "recv": "root@XiaoQiang:~# "}]})
    assert load_recording(path)["steps"][0]["kind"] == "login_ok"


def test_load_recording_未知kind_抛ValueError(tmp_path):
    path = _write(tmp_path, {"steps": [{"kind": "nope", "send": "", "recv": ""}]})
    with pytest.raises(ValueError):
        load_recording(path)


def test_dump_recording_恒写version与kind(tmp_path):
    from modules.router_admin.replay import dump_recording

    path = tmp_path / "rec.json"
    dump_recording(str(path), device="d", firmware="", captured_at="t",
                   steps=[{"send": "a", "recv": "b"}])          # 故意不带 kind
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == RECORD_FORMAT_VERSION
    assert data["steps"] == [{"kind": "command", "send": "a", "recv": "b"}]
