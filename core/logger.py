"""core/logger.py: 集中式日志模块，支持文件输出、内存缓冲、级别筛选。"""
import logging
import os
import sys
import threading
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

from core.constants import DATA_DIR

LOG_DIR = os.path.join(DATA_DIR, "logs")
MAX_MEMORY_LOGS = 5000
MAX_LOG_FILES = 5
MAX_LOG_FILE_SIZE = 5 * 1024 * 1024


class _MemoryHandler(logging.Handler):
    def __init__(self, capacity=MAX_MEMORY_LOGS):
        super().__init__()
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append({
                "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
            })
        except Exception:
            pass

    def get_logs(self, level=None, logger_name=None, keyword=None, limit=500):
        results = list(self.buffer)
        if level:
            results = [r for r in results if r["level"] == level]
        if logger_name:
            results = [r for r in results if r["logger"] == logger_name]
        if keyword:
            kw = keyword.lower()
            results = [r for r in results if kw in r["message"].lower() or kw in r["logger"].lower()]
        return list(reversed(results[-limit:]))

    def clear(self):
        self.buffer.clear()


class _ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelname, "")
        record.colored_levelname = f"{color}{record.levelname:<8}{self.RESET}"
        return super().format(record)


_memory_handler = _MemoryHandler()
_file_handler = None
_initialized = False


def setup_logger(log_dir=None, level=logging.DEBUG):
    global _file_handler, _initialized
    if _initialized:
        return
    _initialized = True

    if log_dir is None:
        log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "yzplan.log")
    try:
        _file_handler = logging.FileHandler(log_file, encoding="utf-8")
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
    except Exception:
        _file_handler = None

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if _file_handler:
        root.addHandler(_file_handler)
    root.addHandler(_memory_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(console)

    _rotate_logs(log_dir)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("feedparser").setLevel(logging.WARNING)

    install_exception_hook()


def _rotate_logs(log_dir):
    try:
        log_file = os.path.join(log_dir, "yzplan.log")
        if not os.path.exists(log_file):
            return
        if os.path.getsize(log_file) > MAX_LOG_FILE_SIZE:
            for i in range(MAX_LOG_FILES - 1, 0, -1):
                src = os.path.join(log_dir, f"yzplan.log.{i}")
                dst = os.path.join(log_dir, f"yzplan.log.{i + 1}")
                if os.path.exists(src):
                    if i + 1 >= MAX_LOG_FILES:
                        os.remove(src)
                    else:
                        os.rename(src, dst)
            os.rename(log_file, os.path.join(log_dir, "yzplan.log.1"))
    except Exception:
        pass


def get_logger(name):
    return logging.getLogger(name)


def get_memory_logs(level=None, logger_name=None, keyword=None, limit=500):
    return _memory_handler.get_logs(level, logger_name, keyword, limit)


def clear_memory_logs():
    _memory_handler.clear()


def get_log_files():
    log_dir = LOG_DIR
    if not os.path.exists(log_dir):
        return []
    files = []
    for f in sorted(os.listdir(log_dir)):
        if f.startswith("yzplan.log"):
            path = os.path.join(log_dir, f)
            size = os.path.getsize(path)
            files.append({"name": f, "path": path, "size": size})
    return files


def read_log_file(path, tail_lines=500):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-tail_lines:]
    except Exception:
        return []


def get_loggers():
    loggers = ["rss_aggregator", "rss_store", "core", "ui", "modules", "root"]
    return sorted(set(loggers))


def get_log_levels():
    return ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def install_exception_hook():
    _original_excepthook = sys.excepthook
    _original_thread_excepthook = getattr(threading, "excepthook", None)

    def _log_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            _original_excepthook(exc_type, exc_value, exc_tb)
            return
        logger = logging.getLogger("exception")
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        logger.error("未捕获异常:\n%s", "".join(tb_lines))

    def _log_thread_exception(args):
        logger = logging.getLogger("exception")
        tb_lines = traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
        logger.error("线程未捕获异常 [%s]:\n%s", args.thread.name, "".join(tb_lines))
        if _original_thread_excepthook:
            _original_thread_excepthook(args)

    sys.excepthook = _log_exception
    try:
        threading.excepthook = _log_thread_exception
    except AttributeError:
        pass
