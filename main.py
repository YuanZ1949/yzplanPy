"""YZplan 程序入口。"""
import logging
import os
import sys

# 进程拉取追踪：记录本进程内所有 subprocess.Popen 调用点与参数，
# 用于排查"启动时又自动拉起了第二个应用实例"等外部进程问题。
try:
    import subprocess as _sp
    import traceback as _tb
    import threading as _th
    _orig_popen = _sp.Popen

    def _traced_popen(*_a, **_k):
        try:
            _popen_log = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "data", "logs", "spawn.log")
            os.makedirs(os.path.dirname(_popen_log), exist_ok=True)
            with open(_popen_log, "a", encoding="utf-8") as _f:
                _f.write(f"\n[{_th.current_thread().name}] Popen args={_a!r} kwargs={_k!r}\n")
                _f.write("".join(_tb.format_stack()))
        except Exception:
            pass
        return _orig_popen(*_a, **_k)

    _sp.Popen = _traced_popen
except Exception:
    pass

# 把 OS 层 stderr（fd 2）重定向到文件：Qt/Chromium 原生错误都写向 stderr，
# 崩溃前的最后一条 C 层消息（如 Qt 的 Fatal/Check failed）是定位崩溃源的关键，
# 必须在本进程产生任何 Qt 输出前完成重定向（QtWebEngineProcess 会继承该句柄）。
try:
    from core.constants import DATA_DIR
    _logs_dir = os.path.join(DATA_DIR, "logs")
    os.makedirs(_logs_dir, exist_ok=True)
    _stderr_fd = os.open(os.path.join(_logs_dir, "stderr.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(_stderr_fd, 2)
    sys.stderr = os.fdopen(2, "a", encoding="utf-8", errors="replace")
except Exception:
    pass

# 单实例互斥量必须放在任何 Qt/PySide6 导入之前：
# 双实例同时启动时，第二个进程若先做了 Qt import 再检查锁，会卡在
# Qt 初始化阶段（可能连带崩溃），永远走不到失败返回。此处先抢锁，
# 抢不到立即硬退出（os._exit），连 Qt 都不导入——秒退、无副作用。
# 注意：必须用 os._exit 而非 sys.exit。解释器 teardown（pydev/site 等
# 退出钩子）在部分 Windows 环境下会挂起，导致"已退出"的进程残留为
# 1 线程僵尸；os._exit 直接结束进程，绝不执行任何清理钩子。
_MUTEX_HANDLE = None
# 重启（core/restart.py 以 --restart 拉起）时跳过单实例检查：
# 旧实例仍持有互斥量并即将退出，此时子进程 CreateMutexW 会返回
# ERROR_ALREADY_EXISTS(183)，若按常规逻辑会误判"已在运行"而硬退出。
_IS_RESTART = "--restart" in sys.argv
if sys.platform == "win32" and not _IS_RESTART:
    try:
        import ctypes
        from ctypes import wintypes as _wtypes
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _k32.CreateMutexW.restype = _wtypes.HANDLE
        _MUTEX_HANDLE = _k32.CreateMutexW(None, True, r"Local\YZplan.yzplan")
        if ctypes.get_last_error() == 183:
            print("YZplan 已有一个实例在运行。")
            os._exit(0)
    except Exception:
        _MUTEX_HANDLE = None

from core.qt_bootstrap import import_qt

PySide6, QtCore, QtGui, QtWidgets = import_qt()

from core.constants import APP_ID, DATA_DIR


def _load_translations(app):
    from core.constants import TRANSLATION_DIR
    import glob
    qms = sorted(glob.glob(os.path.join(TRANSLATION_DIR, "*.qm")))
    for qm in qms:
        translator = QtCore.QTranslator(app)
        if translator.load(qm):
            app.installTranslator(translator)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # 捕获原生层崩溃（段错误）栈，便于定位 Qt/PySide6 层面的闪退
    try:
        import faulthandler
        from core.logger import LOG_DIR
        os.makedirs(LOG_DIR, exist_ok=True)
        _fault_path = os.path.join(LOG_DIR, "crash_faulthandler.log")
        faulthandler.enable(file=open(_fault_path, "a"))
    except Exception:
        pass

    from core.logger import setup_logger
    setup_logger()
    logger = logging.getLogger("core")
    logger.info("YZplan 启动中...")

    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("YZplan")
        except Exception:
            pass

    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # 抑制 Qt 平台层字体警告（DirectWrite 找不到 MS Sans Serif）
    _original_handler = None

    def _qt_msg_handler(msg_type, context, message):
        if "MS Sans Serif" in message or "CreateFontFaceFromHDC" in message:
            return
        if _original_handler:
            _original_handler(msg_type, context, message)

    _original_handler = QtCore.qInstallMessageHandler(_qt_msg_handler)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("YZplan")
    app.setQuitOnLastWindowClosed(False)

    # 彻底禁用自动 GC：防止后台线程（watchdog、webview_monitor、psutil 等）在错误线程回收
    # shiboken/Qt 包装对象导致 access violation。必须在创建任何 Qt 对象、
    # 启动任何后台线程之前调用。
    # gc.disable() 完全关闭自动垃圾回收；gc.freeze() 只冻结当前对象，新对象仍会触发 GC。
    import gc as _gc
    _gc.disable()

    # 先建 QApplication 再导入 qfluentwidgets/UI 模块（图标字体注册依赖 GUI 实例，否则触发字体警告）
    # 抑制 qfluentwidgets Tips 提示（stdout 重定向）
    _old_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        from core.config import AppConfig
        from core.singleinstance import SingleInstance
        from core.theme import apply_app_theme, apply_global_stylesheet, load_wallpaper
        from core.tray import Tray
        from modules.registry import ModuleContext, ModuleRegistry
        from ui.mainwindow import MainWindow
        from ui.home_tab import HomeTab
        from ui.modules_tab import ModulesTab
        from ui.settings_tab import SettingsTab
        from ui.about_tab import AboutTab
    finally:
        sys.stdout.close()
        sys.stdout = _old_stdout

    app.setFont(QtGui.QFont("Microsoft YaHei", 9))
    from qfluentwidgets import setFontFamilies
    setFontFamilies(["Microsoft YaHei", "Segoe UI", "PingFang SC"])

    _load_translations(app)

    si = SingleInstance(DATA_DIR, APP_ID, mutex_handle=_MUTEX_HANDLE)
    if not _IS_RESTART and not si.try_acquire():
        print("YZplan 已有一个实例在运行。")
        # 硬退出：同互斥量分支（main.py 顶部），避免 sys.exit teardown 挂起残留僵尸进程。
        # 若是交互启动，面向用户的海报提示由启动 wrapper（run.bat）负责。
        os._exit(0)
    # 注册给重启模块：重启时先释放锁再拉起新实例，避免双实例竞态
    from core import restart as _restart_mod
    _restart_mod.set_single_instance(si)

    config = AppConfig()
    # 尽早启动 MCP HTTP 服务（若启用），这样即使后续 UI 初始化卡死，也能用
    # 性能监测模块（perf_threads 等工具）远程诊断卡住的线程。
    if config.get("mcp.enabled", False):
        try:
            import threading as _threading
            import mcp_server
            from wsgiref.simple_server import make_server

            def _serve_mcp():
                try:
                    httpd = make_server(
                        "127.0.0.1", 8765,
                        lambda e, s: mcp_server._http_handler(e, s, {}))
                except OSError:
                    return
                httpd.serve_forever()

            _threading.Thread(target=_serve_mcp, daemon=True).start()
        except Exception:
            pass

    apply_app_theme(config.get("ui.theme", "auto"))
    apply_global_stylesheet(config.get("ui.acrylic", False))
    load_wallpaper(config.get("ui.wallpaper", ""))
    context = ModuleContext(config=config, host_window=None, app=app)
    context.registry = ModuleRegistry(context)
    context.si = si

    mw = MainWindow(context)
    context.host_window = mw
    mw.setup(HomeTab(context), ModulesTab(context), SettingsTab(context), AboutTab(context))

    tray = Tray(mw.window, on_show_home=mw.show, on_quit=mw.quit, context=context)
    mw.attach_tray(tray)
    context.tray = tray

    # MCP 通知收件箱监听：让 MCP 接口可以往运行中的 GUI 发托盘通知
    _mcp_inbox = os.path.join(DATA_DIR, "mcp_inbox")
    try:
        if os.path.isdir(_mcp_inbox):
            for _f in os.listdir(_mcp_inbox):
                if _f.endswith(".json"):
                    try:
                        os.remove(os.path.join(_mcp_inbox, _f))
                    except OSError:
                        pass
    except OSError:
        pass
    tray.start_mcp_inbox_watcher(_mcp_inbox)

    context.registry.start_enabled()

    if not config.get("window.start_hidden", False):
        mw.show()

    # 卡死排查：常驻守护线程记录主线程栈 + 主线程心跳
    try:
        import core.perf as _perf
        _perf.start_watchdog()
        _hb_timer = QtCore.QTimer()
        _hb_timer.timeout.connect(_perf.heartbeat)
        _hb_timer.setInterval(1000)
        _hb_timer.start()
    except Exception:
        pass

    # 定期在主线程手动执行 gc.collect()，清理循环垃圾。
    # gc.disable() 已在创建 QApplication 后立即调用，彻底禁用自动 GC，
    # 防止后台线程自动触发 GC 回收 Qt 对象。
    def _safe_gc_collect():
        # 只要有存活的 QtWebEngine 预览，就跳过本次强制收集——强制回收其
        # shiboken 包装会在渲染子进程仍引用它时触发 0x8001010d/Aborted 崩溃。
        try:
            import core.perf as _perf
            if _perf.webengine_alive():
                return
        except Exception:
            pass
        _gc.collect()

    _gc_timer = QtCore.QTimer()
    _gc_timer.timeout.connect(_safe_gc_collect)
    _gc_timer.setInterval(120_000)
    _gc_timer.start()

    # GC 监测：记录手动 gc.collect() 触发的回收情况。
    try:
        import threading as _th
        import time as _time
        _gc_last = {"t": 0.0}
        _gc_main_tid = _th.get_ident()

        def _on_gc(phase, info):
            if _time.time() - _gc_last["t"] < 5.0:
                return
            if phase == "start":
                tid = _th.get_ident()
                if tid == _gc_main_tid:
                    return
                _gc_last["t"] = _time.time()
                logging.getLogger("core").warning(
                    "GC 在非主线程启动 thread=%s tid=%s（存在回收 Qt 对象导致崩溃的风险）",
                    _th.current_thread().name, tid)
            elif phase == "stop":
                collected = info.get("collected", 0)
                gen = info.get("generation", -1)
                if collected and info.get("generation", 0) and _th.get_ident() != _gc_main_tid:
                    _gc_last["t"] = _time.time()
                    logging.getLogger("core").warning(
                        "非主线程 GC 回收 gen=%s collected=%s", gen, collected)

        _gc.callbacks.clear()
        _gc.callbacks.append(_on_gc)
    except Exception:
        pass

    exit_code = app.exec()
    try:
        context.registry.stop_all()
    finally:
        si.release()
    # 直接退出进程：绕过 CPython 解释器收尾 + shiboken/Qt 对象析构，
    # 这两步在 Windows 上常引发退出期 access violation（crash 日志常见）。
    os._exit(exit_code)


if __name__ == "__main__":
    sys.exit(main())