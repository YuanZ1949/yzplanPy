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


class _SilentBackend:
    """写操作石沉大海（模拟无权限）；读操作按构造参数报告「旧状态」。"""

    def __init__(self, *, get=None, keys=None):
        self._get = get
        self._keys = list(keys or [])

    def get(self, hive, path, name=None):
        return self._get

    def set(self, hive, path, name, value):
        return None

    def delete(self, hive, path, name=None):
        return None

    def delete_tree(self, hive, path):
        return None

    def list_keys(self, hive, path):
        return list(self._keys)

    def list_values(self, hive, path):
        return []


def test_exec_ops_reports_write_failure():
    """controller 裁定（T2 评审）：写失败必须被回读校验抓出。

    `Win32Backend` 的 never-raise 契约让「无权限」与「成功」在返回值上无法区分，
    只写不校验时 HKLM 未提权会报「全部成功」，上层账本随之记录没发生的改动。
    三条原语各钉一个失败侧：set/delete 由 `get` 的返回值判定，delete_tree 由
    `list_keys` 判定——少任何一条校验，本用例的对应断言就会红。
    """
    results = elevate.exec_ops(
        _SilentBackend(get=None), [elevate.set_op("hkcu", r"k", "x", "v")])
    assert results[0]["ok"] is False and results[0]["error"] == "write_failed"

    results = elevate.exec_ops(
        _SilentBackend(get="still-there"), [elevate.delete_op("hkcu", r"k", "x")])
    assert results[0]["ok"] is False and results[0]["error"] == "write_failed"

    results = elevate.exec_ops(
        _SilentBackend(keys=["stale"]), [elevate.delete_tree_op("hklm", r"k")])
    assert results[0]["ok"] is False and results[0]["error"] == "write_failed"


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


def test_menu_action_from_argv_parses_and_fallbacks():
    """--menu-action 取下一个 argv；缺值/缺参数/空串一律归一为 ""，绝不抛。"""
    assert elevate.menu_action_from_argv(["x", "--menu-action", "open_manager"]) == "open_manager"
    assert elevate.menu_action_from_argv(["x"]) == ""
    assert elevate.menu_action_from_argv(["--menu-action"]) == ""          # 缺值
    assert elevate.menu_action_from_argv(["--menu-action", ""]) == ""      # 空动作
    assert elevate.menu_action_from_argv([]) == ""                        # 不抛


def test_forward_menu_action_from_argv_routes(monkeypatch):
    """单实例转发入口：解析 argv → forward_menu_action；无动作则不转发并返回 False。"""
    seen = []
    monkeypatch.setattr(elevate, "forward_menu_action",
                        lambda a, **kw: seen.append(a) or True)
    assert elevate.forward_menu_action_from_argv(["p", "--menu-action", "restore_all"]) is True
    assert seen == ["restore_all"]
    seen.clear()
    assert elevate.forward_menu_action_from_argv(["p"]) is False
    assert seen == []


def test_main_reuses_elevate_argv_helpers():
    """I-3 收尾：main.py 两处 --menu-action 解析必须走 elevate 的单一 helper。

    入口文件有两处读 `--menu-action`（单实例 183 分支转发、首实例 pending 待办）。
    判据是结构性的（AST），不是运行时的——main.py 有顶层副作用（抢互斥量、
    os._exit），无法在测试进程里 import。两侧各钉一条：
      1. 两个 helper 都被调用（接线存在，删掉任一即红）；
      2. 不得出现 `sys.argv.index("--menu-action")` 式的内联重复实现
         （重复解析正是 I-3 要消灭的东西；`--elevated-job` 的内联解析是既有
         早退通道，不在管辖范围，故只针对 `--menu-action` 字面量）。
    """
    import ast

    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "main.py")
    src = open(main_py, encoding="utf-8").read()
    tree = ast.parse(src)

    called = set()
    inline_menu_index = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
            if (isinstance(func, ast.Attribute) and func.attr == "index"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "--menu-action"):
                inline_menu_index = True

    assert "forward_menu_action_from_argv" in called, "183 分支必须调用转发 helper"
    assert "menu_action_from_argv" in called, "main() 必须调用 argv 解析 helper"
    assert inline_menu_index is False, "--menu-action 解析不得在 main.py 内联重复实现"
