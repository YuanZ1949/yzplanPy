"""Single instance lock.

Windows 上使用内核命名互斥量（CreateMutexW）：进程异常退出（崩溃/被杀死）
时内核自动释放句柄，不存在锁文件残留/过期的坑；同时保证同一用户只能跑一个实例。
"""
import ctypes
import os
import sys

try:
    from ctypes import wintypes
except Exception:  # 非 Windows
    wintypes = None

_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, app_dir, app_id="yzplan", mutex_handle=None):
        self._mutex = None
        self._kernel32 = None
        if mutex_handle is not None:
            # main.py 已在任何 Qt 导入前抢好了互斥量，这里复用该句柄
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._mutex = mutex_handle
            self._pre_acquired = True
        elif wintypes is not None:
            try:
                self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                self._mutex = self._kernel32.CreateMutexW(
                    None, True, f"Local\\YZplan.{app_id}")
            except Exception:
                self._kernel32 = None
                self._mutex = None
        self._lock_path = os.path.join(app_dir, f"{app_id}.lock")

    def try_acquire(self):
        # main.py 预先创建的句柄已在任何 Qt 导入前获得所有权
        if self._mutex is not None and getattr(self, "_pre_acquired", False):
            return True
        if self._kernel32 is not None and self._mutex:
            err = ctypes.get_last_error()
            if err == _ERROR_ALREADY_EXISTS:
                return False
            # 其他错误（如系统资源不足）时也视为持有失败但可重试
            return err == 0 or self._mutex
        # 回退：QLockFile（注意 stale 时间给正常值，避免 0 导致永远可获取）
        from .qt_bootstrap import import_qt
        _, QtCore, _, _ = import_qt()
        self._lock = QtCore.QLockFile(self._lock_path)
        self._lock.setStaleLockTime(30000)
        return self._lock.tryLock(100)

    def release(self):
        if self._kernel32 is not None and self._mutex:
            try:
                self._kernel32.ReleaseMutex(self._mutex)
                self._kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None
            return
        try:
            self._lock.unlock()
        except Exception:
            pass