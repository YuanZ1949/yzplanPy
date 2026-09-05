"""core/restart.py: 重启应用程序，支持 exe 模式和开发模式。"""
import os
import subprocess
import sys

# 由 main.py 在获取单实例锁后注册，供重启使用。
_SI = None


def set_single_instance(si):
    global _SI
    _SI = si


def restart_app():
    """拉起新实例（--restart）后退出当前实例。

    不再先释放单实例锁再拉起：释放后互斥量对象仍存在，新进程
    CreateMutexW 会收到 ERROR_ALREADY_EXISTS(183) 而误判"已在运行"退出；
    且释放瞬间其他潜伏进程可能与新实例抢占锁，产生双实例/僵尸进程。
    改为保持持锁、以 --restart 拉起子进程（子进程跳过单实例检查），
    由当前实例退出后接管——无需临时释放窗口。
    """
    from core.constants import PROJECT_DIR

    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
        cwd = os.path.dirname(sys.executable)
    else:
        venv_dir = os.path.join(PROJECT_DIR, ".venv", "Scripts")
        pythonw = os.path.join(venv_dir, "pythonw.exe")
        if os.path.exists(pythonw):
            cmd = [pythonw]
        else:
            cmd = [sys.executable]
        cmd.append(os.path.join(PROJECT_DIR, "main.py"))
        cwd = PROJECT_DIR

    if "--restart" not in cmd:
        cmd.append("--restart")

    subprocess.Popen(cmd, cwd=cwd)

    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    QtWidgets.QApplication.quit()