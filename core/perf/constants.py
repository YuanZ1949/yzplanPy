"""core/perf: 性能监测常量与全局状态（开关、记录桶、时间基准、WebEngine 标记）。"""
import os
import threading
import time
from collections import defaultdict, deque
from ..constants import DATA_DIR

PERF_LOG_DIR = os.path.join(DATA_DIR, "logs")
PERF_CSV_PATH = os.path.join(PERF_LOG_DIR, "perf_stats.csv")
PERF_ENABLED_KEY = "performance.enabled"

_lock = threading.Lock()
_records = defaultdict(lambda: deque(maxlen=1000))  # name -> deque[(duration, time)]
_enabled = True
_start_time = time.time()

MAX_HEAD = 500

# WebEngine 预览常驻标记：只要有 QtWebEngine 预览对象存活，就禁止任何位置
# 强制的 gc.collect()（回收其 shiboken 包装会在渲染子进程仍引用时导致
# 0x8001010d / Aborted 崩溃）。由 rss_aggregator 在创建/销毁预览时切换，
# 由主线程定期 GC 定时器在此处查询后才决定是否收集。
_webengine_alive = False
