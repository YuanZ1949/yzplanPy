"""core/restart.py: 重启应用程序，支持 exe 模式和开发模式。"""
import logging
import os
import subprocess
import sys
import threading

_log = logging.getLogger("restart")

# 由 main.py 在获取单实例锁后注册，供重启使用。
_SI = None

# 旧实例退出兜底延时（秒）：QApplication.quit() 若未能终止事件循环，
# 到点后强制硬退出，避免旧实例残留、与新实例并存（双实例/双份抓取）。
_FORCE_EXIT_AFTER = 2.0


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

    退出采用双保险：先 QApplication.quit() 走正常退出路径；另起一个非守护
    线程定时器，到点直接 os._exit(0)。正常路径下 app.exec() 返回后 main()
    末尾的 os._exit 会先执行，定时器不会触发；若 quit() 未能终止事件循环
    （实测出现过：重启后旧实例残留），兜底定时器保证旧实例必定退出。
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

    _log.info("重启：拉起新实例 cmd=%s cwd=%s", cmd, cwd)
    try:
        subprocess.Popen(cmd, cwd=cwd)
    except Exception:
        _log.exception("重启：拉起新实例失败，保持当前实例继续运行")
        raise
    _log.info("重启：新实例已拉起，准备退出当前实例")

    threading.Timer(_FORCE_EXIT_AFTER, lambda: os._exit(0)).start()

    try:
        from core.qt_bootstrap import import_qt
        _, _, _, QtWidgets = import_qt()
        QtWidgets.QApplication.quit()
        _log.info("重启：已请求退出当前实例（QApplication.quit）")
    except Exception:
        _log.exception("重启：QApplication.quit() 异常，硬退出当前实例")
        os._exit(0)