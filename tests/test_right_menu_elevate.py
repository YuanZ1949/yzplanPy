"""提权作业通道：序列化/执行/超时/UAC 取消映射/main 早退端到端/Qt 隔离。"""
import json, os, subprocess, sys

from modules.right_menu import elevate
from modules.right_menu.registry_backend import FakeRegistry


def test_exec_ops_primitives():
    r = FakeRegistry()
    r.set("hkcu", r"k\b", "x", "1")
    r.set("hkcu", r"k\c\deep", "y", "1")
    results = elevate.exec_ops(r, [
        elevate.set_op("hkcu", r"k\a", "", "v"),
        elevate.delete_op("hkcu", r"k\b", "x"),
        elevate.delete_tree_op("hkcu", r"k\c"),
    ])
    assert all(x["ok"] for x in results)
    assert r.get("hkcu", r"k\a") == "v"
    assert r.get("hkcu", r"k\b", "x") is None
    assert r.get("hkcu", r"k\c\deep", "y") is None


def test_exec_ops_reports_write_failure():
    """controller 裁定（T2 评审）：写失败必须被回读校验抓出——Win32Backend 的
    never-raise 契约会让 HKLM 未提权的写入静默无声，只回读就永远报成功。"""
    class _SilentSetStub:
        """set 是静默 no-op（模拟无权限写入失败），get 恒 None。"""
        def get(self, hive, path, name=None):
            return None
        def set(self, hive, path, name, value):
            return None
        def delete(self, hive, path, name=None):
            return None
        def delete_tree(self, hive, path):
            return None
        def list_keys(self, hive, path):
            return []
        def list_values(self, hive, path):
            return []

    results = elevate.exec_ops(
        _SilentSetStub(), [elevate.set_op("hkcu", r"k", "x", "v")])
    assert results[0]["ok"] is False
    assert results[0]["error"] == "write_failed"


def test_run_elevated_job_roundtrip(tmp_path):
    r = FakeRegistry()
    job_path = str(tmp_path / "job_t1.json")
    json.dump({"id": "t1", "ops": [elevate.set_op("hkcu", r"k", "name", "val")]},
              open(job_path, "w", encoding="utf-8"))
    assert elevate.run_elevated_job(job_path, backend=r) == 0
    result = json.load(open(str(tmp_path / "job_t1.result.json"), encoding="utf-8"))
    assert result["ok"] is True and r.get("hkcu", r"k", "name") == "val"


def test_run_elevated_job_missing_file_returns_1(tmp_path):
    assert elevate.run_elevated_job(str(tmp_path / "nope.json"), backend=FakeRegistry()) == 1


def test_run_job_reads_child_result(tmp_path, monkeypatch):
    monkeypatch.setattr(elevate, "JOB_DIR", str(tmp_path / "elevated"))

    def fake_launch(job_path, **kw):        # 模拟提权子进程立即写结果
        jid = json.load(open(job_path, encoding="utf-8"))["id"]
        json.dump({"id": jid, "ok": True, "error": None},
                  open(elevate._result_path(jid), "w", encoding="utf-8"))
        return {"ok": True, "error": None, "code": 42}

    out = elevate.run_job({"ops": []}, timeout=2.0, launch_fn=fake_launch, poll_interval=0.05)
    assert out["ok"] is True


def test_run_job_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(elevate, "JOB_DIR", str(tmp_path / "elevated"))
    out = elevate.run_job({"ops": []}, timeout=0.3,
                          launch_fn=lambda p, **k: {"ok": True, "error": None, "code": 42},
                          poll_interval=0.05)
    assert out["ok"] is False and out["error"] == "timeout"


def test_build_launch_cmd_frozen_and_dev(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = elevate.build_launch_cmd(r"C:\tmp\j.json")
    assert cmd[0] == sys.executable and cmd[-2:] == ["--elevated-job", r"C:\tmp\j.json"]
    monkeypatch.delattr(sys, "frozen")
    cmd = elevate.build_launch_cmd(r"C:\tmp\j.json")
    assert any(str(x).endswith("main.py") for x in cmd) and cmd[-2:] == ["--elevated-job", r"C:\tmp\j.json"]


def test_launch_maps_cancel_and_success():
    out = elevate.launch(r"C:\tmp\j.json", shell_execute=lambda exe, params, cwd: 5)
    assert out["ok"] is False and out["error"] == "cancelled"    # SE_ERR_ACCESSDENIED：用户点了“否”
    out = elevate.launch(r"C:\tmp\j.json", shell_execute=lambda exe, params, cwd: 42)
    assert out["ok"] is True


def test_forward_menu_action_writes_inbox(tmp_path):
    assert elevate.forward_menu_action("open_manager", inbox_dir=str(tmp_path))
    name = [f for f in os.listdir(tmp_path) if f.endswith(".json")][0]
    payload = json.load(open(os.path.join(tmp_path, name), encoding="utf-8"))
    assert payload["command"] == "menu_action" and payload["action"] == "open_manager"


def test_import_elevate_does_not_load_qt():
    code = ("import sys; import modules.right_menu.elevate; "
            "mods = set(sys.modules); "
            "assert not any(m.startswith('PySide6') for m in mods), 'PySide6 loaded'; "
            "assert 'qfluentwidgets' not in mods and 'core.qt_bootstrap' not in mods; "
            "print('OK')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    assert "OK" in out.stdout


def test_main_early_exit_channel(tmp_path):
    """main.py --elevated-job 必须在 Qt/互斥量之前早退并写结果（端到端）。"""
    job_path = tmp_path / "job_e2e.json"
    job_path.write_text(json.dumps({"id": "e2e", "ops": []}), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "main.py", "--elevated-job", str(job_path)],
                         capture_output=True, text=True, cwd=os.getcwd(), env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    result = json.loads((tmp_path / "job_e2e.result.json").read_text(encoding="utf-8"))
    assert result["ok"] is True
