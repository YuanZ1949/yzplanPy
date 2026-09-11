import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.sys_info import collect_info


def test_collect_info_keys():
    info = collect_info()
    for key in ("系统", "处理器", "内存总量", "GPU", "主机名"):
        assert key in info
    assert len(info) >= 8


def test_collect_info_extended_keys():
    """Task 10: collect_info 追加 Python/网络/启动时间/IO 等新字段。"""
    info = collect_info()
    for key in ("Python版本", "PySide6版本", "qfluentwidgets版本",
                "网络适配器", "系统启动时间", "磁盘IO"):
        assert key in info
        assert info[key], f"{key} 不应为空"
    # 新字段必须追加在原有字段之后
    keys = list(info)
    assert keys.index("Python版本") > keys.index("系统盘")