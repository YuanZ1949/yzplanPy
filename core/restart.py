"""core/restart.py: 重启应用程序，支持 exe 模式和开发模式。"""
import os
import subprocess
import sys


def restart_app():
    """释放单实例锁并重启应用程序。"""
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

    subprocess.Popen(cmd, cwd=cwd)

    from core.qt_bootstrap import import_qt
    _, _, _, QtWidgets = import_qt()
    QtWidgets.QApplication.quit()
