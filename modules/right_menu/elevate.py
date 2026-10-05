"""right_menu 提权作业通道：作业文件序列化 + `--elevated-job` 早退执行。

HKLM 写入需要管理员权限，但 GUI 进程不能整体提权（会把整个 Qt 应用连同单实例
互斥量一起拉起）。做法是把注册表原语序列化成**作业文件** `{"id","ops":[...]}`，用
ShellExecuteW("runas") 拉起同一可执行文件的第二个实例；该实例由 main.py 顶部早退
通道接手，只执行原语、写结果文件、立即退出——不创建 QApplication、不抢单实例互斥
量，因此与正在运行的主实例互不冲突（这也是早退通道必须排在互斥量之前的原因）。

三条不变量：
  * **Qt-free**：本文件是 `--elevated-job` 早退通道最先 import 的代码，禁 import
    PySide6 / qfluentwidgets / module.py（`test_import_elevate_does_not_load_qt` 守门）。
  * **调用时读全局**：`JOB_DIR` / `DATA_DIR` 一律在函数体内读取（测试 monkeypatch
    后立即生效），绝不固化进闭包或默认参数。
  * **依赖方向单向**：`elevate → elevate_ops`（原语与回读校验，后者 Qt-free 且不反向
    import 本文件）。作业 ops 的形状与「写后回读校验」在 `elevate_ops.py`——它只做
    「一条 op → 一个结果条目」，不认识作业文件/子进程/UAC；`JOB_DIR` 与全部读它的
    函数留在本文件。公开的原语/执行入口在下方转出，调用方一律走 `elevate.*`。
"""
import json, os, subprocess, sys, time, uuid

from core.constants import DATA_DIR

from .elevate_ops import delete_op, delete_tree_op, exec_ops, set_op

__all__ = ["JOB_DIR", "set_op", "delete_op", "delete_tree_op", "exec_ops",
           "run_elevated_job", "build_launch_cmd", "launch", "run_job",
           "menu_action_command", "forward_menu_action"]

# 作业/结果文件目录：job_<id>.json 与 job_<id>.result.json 成对落在同一目录。
# 刻意不自动清理——提权失败/UAC 被取消时，这两个文件是唯一的排查现场。
JOB_DIR = os.path.join(DATA_DIR, "right_menu", "elevated")


# ── 作业 / 结果文件 ───────────────────────────────────────────────────
def _job_path(job_id):
    """作业文件路径（调用时读 JOB_DIR，测试 monkeypatch 后立即生效）。"""
    return os.path.join(JOB_DIR, f"job_{job_id}.json")


def _result_path(job_id):
    """结果文件路径：与作业文件同目录、同 stem、换后缀（job_x.json → job_x.result.json）。"""
    return os.path.splitext(_job_path(job_id))[0] + ".result.json"


def _result_path_of(job_path):
    """由命令行给出的作业文件路径推出结果文件路径（提权侧不经过 JOB_DIR）。"""
    return os.path.splitext(job_path)[0] + ".result.json"


def _write_json(path, payload):
    """原子写：先写 .tmp 再 os.replace，子进程被强杀也不留半文件。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(path + ".tmp", path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _read_json(path):
    """读 JSON；文件不存在或尚未写完（半文件）时返回 None（=「还没写」）。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def run_elevated_job(job_path, *, backend=None):
    """提权子进程侧入口：读作业 → 执行原语 → 写结果文件 → 返回进程退出码。

    退出码 0 全成功 / 1 失败。作业文件根本读不出来时**不写**结果文件：父进程只能
    等超时，而「作业文件不存在」本身就是最好的排查线索，写一个 ok=False 反而把它
    伪装成一次正常的失败执行。
    """
    job = _read_json(job_path)
    if not isinstance(job, dict):
        return 1
    job_id = str(job.get("id") or "")      # 同 elevate_ops._text 的 None→"" 语义
    ops = job.get("ops")
    if not isinstance(ops, list):
        _write_json(_result_path_of(job_path),
                    {"id": job_id, "ok": False, "error": "bad_job", "results": []})
        return 1
    if backend is None:
        from .registry_backend import Win32Backend
        backend = Win32Backend()            # 惰性：只有提权进程真去碰注册表
    results = exec_ops(backend, ops)
    error = next((r.get("error") for r in results if not r.get("ok")), None)
    _write_json(_result_path_of(job_path),
                {"id": job_id, "ok": error is None, "error": error, "results": results})
    return 0 if error is None else 1


# ── 拉起提权子进程 ─────────────────────────────────────────────────────
def build_launch_cmd(job_path):
    """子进程命令行，镜像 core/restart.py 的 exe/开发双模式。

    开发模式优先用 pythonw.exe：拉起的是提权后的黑窗，用户点了「否」或作业失败
    都不该在桌面上留一个控制台窗口；没有 pythonw 才退回 sys.executable。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--elevated-job", job_path]
    from core.constants import PROJECT_DIR
    pythonw = os.path.join(PROJECT_DIR, ".venv", "Scripts", "pythonw.exe")
    cmd = [pythonw if os.path.exists(pythonw) else sys.executable]
    cmd.append(os.path.join(PROJECT_DIR, "main.py"))
    cmd.extend(["--elevated-job", job_path])
    return cmd


def _launch_cwd():
    """子进程工作目录：exe 模式取 exe 目录，开发模式取项目根（同 restart.py）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    from core.constants import PROJECT_DIR
    return PROJECT_DIR


def _shell_execute_runas(exe, params, cwd):
    """ShellExecuteW("runas") 提权拉起；任何异常（含非 Windows 无 windll）→ 0。"""
    try:
        import ctypes
        return int(ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1) or 0)
    except Exception:
        return 0


def launch(job_path, *, shell_execute=None):
    """提权拉起子进程 → {"ok", "error", "code"}。

    ShellExecute 的约定是**返回值 > 32 才算成功**（≤32 为错误码）。其中 5 =
    ERROR_ACCESS_DENIED，即用户在 UAC 对话框点了「否」——这是用户主动取消而非
    故障，映射成 error="cancelled"，UI 可以安静地不弹任何报错。
    """
    cmd = build_launch_cmd(job_path)
    try:
        code = int((shell_execute or _shell_execute_runas)(
            cmd[0], subprocess.list2cmdline(cmd[1:]), _launch_cwd()) or 0)
    except Exception:
        code = 0
    if code > 32:
        return {"ok": True, "error": None, "code": code}
    return {"ok": False, "error": "cancelled" if code == 5 else "launch_failed", "code": code}


def run_job(job, *, timeout=60.0, launch_fn=None, poll_interval=0.2):
    """写作业 → 提权拉起 → 轮询结果文件 → 结果 dict（必含 "ok"）。

    轮询而非 waitpid：ShellExecute 拉起的提权进程没有可等待的进程句柄，父子之间
    唯一的通信介质就是结果文件。作业与结果文件都**不删除**——提权失败或 UAC 被取消
    时它们是唯一的排查现场。
    """
    job_id = uuid.uuid4().hex
    ops = job.get("ops") if isinstance(job, dict) else None
    payload = {"id": job_id, "ops": list(ops or [])}
    job_path = _job_path(job_id)
    if not _write_json(job_path, payload):
        return {"ok": False, "error": "job_write_failed", "id": job_id}
    out = (launch_fn or launch)(job_path)
    if not isinstance(out, dict) or not out.get("ok"):
        return dict(out or {}, ok=False, error=(out or {}).get("error") or "launch_failed",
                    id=job_id)
    result_path, deadline = _result_path(job_id), time.monotonic() + timeout
    while True:
        data = _read_json(result_path)
        if isinstance(data, dict):
            data.setdefault("ok", False)     # 结果文件由子进程写，缺 ok 时按失败算
            data.setdefault("error", None)
            return data
        if time.monotonic() >= deadline:
            return {"ok": False, "error": "timeout", "id": job_id}
        time.sleep(poll_interval)


# ── 右键菜单动作转发（提权进程 → 运行中的主实例）────────────────────────
def menu_action_command(action):
    """构造 inbox 命令（形状对齐 mcp_server 的 _mcp_inbox_command）。

    提权进程不能弹窗也不能改主实例的内存，只能往 inbox 丢文件，由主实例的托盘
    轮询器消费——复用 MCP 已有的那条 IPC 路，不新增第二套机制。
    """
    return {"id": uuid.uuid4().hex, "command": "menu_action",
            "action": str(action or ""),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "silent": True}


def forward_menu_action(action, *, inbox_dir=None):
    """把动作写进 inbox → True；目录不可写等任何异常 → False（绝不抛）。"""
    try:
        target = inbox_dir or os.path.join(DATA_DIR, "mcp_inbox")
        os.makedirs(target, exist_ok=True)
        payload = menu_action_command(action)
        with open(os.path.join(target, f"{payload['id']}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return True
    except Exception:
        return False
