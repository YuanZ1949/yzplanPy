"""proxy_ctrl 的代理目标协议：TargetResult 与 ProxyTarget。

从 targets.py 原子切出。起因是 Docker 分支也要实现同一套协议，
若它放在 targets.py 内部，targets ↔ target_docker 就会循环 import。
两者都改为依赖本文件，targets.py 再原样 re-export，公开 API 不变。
"""


class TargetResult:
    """一次写操作的结果。ok=False 时 message 面向用户直接展示。"""

    def __init__(self, ok, message, detail=""):
        self.ok = bool(ok)
        self.message = message
        self.detail = detail

    def __bool__(self):
        return self.ok

    def __repr__(self):  # pragma: no cover - 调试用
        return f"TargetResult(ok={self.ok}, message={self.message!r})"


class ProxyTarget:
    """代理目标协议。"""

    id = ""
    name = ""
    note = ""

    def read(self):
        """当前代理值；未设置返回 None。"""
        raise NotImplementedError

    def set(self, url):
        raise NotImplementedError

    def unset(self):
        raise NotImplementedError
