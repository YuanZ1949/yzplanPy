import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.sys_info import collect_info


def test_collect_info_keys():
    info = collect_info()
    for key in ("系统", "处理器", "内存总量", "GPU", "主机名"):
        assert key in info
    assert len(info) >= 8