"""回归：QtWebEngine 必须保持惰性加载。

在离屏模式下加载主要模块（含 RSS 聚合、页面选择器），断言
PySide6.QtWebEngine* 不会因此进入 sys.modules——避免启动期即拉起
Chromium 线程池（本机一次性产生 ~70-90 个常驻空闲原生线程）。
仅在首次创建预览/选择器视图时才允许加载这些模块。
参见 docs/开发日志 2026-09-05。

注意：环境纯度断言在【独立子进程】中执行，以避免与同进程内其它
测试（如 test_mcp 会触发 screenshot_core 合法急切加载 WebEngine）造成
sys.modules 全局污染相互干扰，从而对收集顺序 / 执行顺序鲁棒。
"""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

import modules.rss_aggregator as rss_aggregator
import modules.page_selector as page_selector
import modules.rss_store as rss_store

_WEBENGINE_MODULES = (
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 在全新解释器进程中复现"启动期导入主模块"场景，检查是否泄漏 WebEngine。
# 用子进程隔离：父进程里其它测试（例如 test_mcp 触发的 screenshot_core）
# 会合法地把 QtWebEngine 加入 sys.modules，若在本进程做全局 sys.modules
# 断言，结果会对收集/执行顺序敏感而误报。
_FRESH_PROCESS_CHECK = r"""
import os, sys
sys.path.insert(0, os.environ["YZPLAN_PROJECT_ROOT"])
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
_ = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import modules.rss_aggregator
import modules.page_selector
import modules.rss_store
names = ("PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore")
leaked = [n for n in names if n in sys.modules]
if leaked:
    sys.stderr.write("LEAKED:" + ",".join(leaked))
    sys.exit(1)
sys.exit(0)
"""


def _webengine_stays_lazy_in_fresh_process() -> bool:
    """子进程全新解释器导入主模块，返回是否无 WebEngine 泄漏。"""
    env = dict(os.environ)
    env["YZPLAN_PROJECT_ROOT"] = _PROJECT_ROOT
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_PROCESS_CHECK],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if proc.returncode == 0:
        return True
    if "LEAKED:" in proc.stderr:
        return False
    # 非泄漏类失败（Qt 初始化异常等）——向上抛，避免把环境故障误判为"通过"。
    raise RuntimeError(
        "子进程纯度检查失败（非 WebEngine 泄漏）：\n"
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


def test_webengine_not_imported_after_modules_load():
    assert _webengine_stays_lazy_in_fresh_process(), (
        "启动期导入 rss_aggregator / page_selector / rss_store 不应加载 QtWebEngine"
    )


def test_page_selector_import_has_no_webengine_side_effect():
    # 回归：page_selector.py 的 WebEngine 导入已改为惰性（此前为模块级导入）
    assert _webengine_stays_lazy_in_fresh_process(), (
        "page_selector 导入不应带来 WebEngine 副作用"
    )


def test_webengine_still_available_lazily():
    # 惰性 getter 在真正需要时应能拿到 QWebEngineView（不因重构而失效）
    assert page_selector._webengine_view() is not None
    assert "PySide6.QtWebEngineWidgets" in sys.modules
