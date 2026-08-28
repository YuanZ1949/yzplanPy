"""Single instance lock using QLockFile."""
import os

from .qt_bootstrap import import_qt


class SingleInstance:
    def __init__(self, app_dir, app_id="yzplan"):
        _, QtCore, _, _ = import_qt()
        lock_path = os.path.join(app_dir, f"{app_id}.lock")
        self._lock = QtCore.QLockFile(lock_path)
        self._lock.setStaleLockTime(0)

    def try_acquire(self):
        return self._lock.tryLock(100)

    def release(self):
        try:
            self._lock.unlock()
        except Exception:
            pass