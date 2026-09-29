"""proxy_ctrl/targets：七类代理目标的「读 / 设 / 清」矩阵。

移植自 toggle_proxy 的 modules/config.ps1（Windows 分支），但把每个目标
收敛成同一个 ProxyTarget 协议，便于逐项单测与 UI 统一渲染。

- Git      → git config --global（本来就持久化）
- curl/python/wget/node/global → HKCU 用户环境变量（见 envstore）
- Docker   → daemon.json 的 proxies 节点（实现在 target_docker，此处转出）

Docker 分支因自带一套 JSON 读写与降级逻辑已原子切到 target_docker.py，
本模块继续原样 re-export `DockerTarget` / `docker_paths`，
`from .targets import DockerTarget` 等既有调用点不受影响。
"""
import shutil
import subprocess

from . import envstore
from .target_base import ProxyTarget, TargetResult  # noqa: F401  (公开转出)
from .target_docker import DockerTarget, docker_paths  # noqa: F401  (公开转出)

__all__ = [
    "TargetResult", "ProxyTarget", "GitTarget", "EnvTarget",
    "CompositeTarget", "DockerTarget", "docker_paths", "all_targets",
    "GIT_PROXY_KEYS", "CURL_KEYS", "WGET_KEYS", "PYTHON_KEYS",
    "NODE_KEYS", "GLOBAL_KEYS",
]

GIT_PROXY_KEYS = ("http.proxy", "https.proxy")

CURL_KEYS = ("http_proxy", "https_proxy")
WGET_KEYS = ("WGET_PROXY",)
PYTHON_KEYS = ("http_proxy", "https_proxy")
NODE_KEYS = ("HTTP_PROXY", "HTTPS_PROXY")
GLOBAL_KEYS = ("http_proxy", "https_proxy", "socks_proxy",
               "WGET_PROXY", "HTTP_PROXY", "HTTPS_PROXY")


def run_git(args):
    """执行 git。返回 (returncode, stdout, stderr)；git 不存在时 rc 为 -1。"""
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace")
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


class GitTarget(ProxyTarget):
    """Git 全局代理。"""

    id = "git"
    name = "Git"
    note = "写入 git config --global"

    def __init__(self, runner=None, which=None):
        self._run = runner or run_git
        self._which = which or shutil.which

    def available(self):
        return self._which("git") is not None

    def read(self):
        if not self.available():
            return None
        for key in GIT_PROXY_KEYS:
            rc, out, _err = self._run(["config", "--global", "--get", key])
            if rc == 0 and out:
                return out
        return None

    def set(self, url):
        if not self.available():
            return TargetResult(False, "未检测到 Git，已跳过")
        failed = []
        for key in GIT_PROXY_KEYS:
            rc, _out, err = self._run(["config", "--global", key, url])
            if rc != 0:
                failed.append(f"{key}: {err}")
        if failed:
            return TargetResult(False, "Git 代理设置失败", "; ".join(failed))
        return TargetResult(True, "Git 代理已设置")

    def unset(self):
        if not self.available():
            return TargetResult(False, "未检测到 Git，已跳过")
        for key in GIT_PROXY_KEYS:
            # --unset 对不存在的键返回非 0，属正常情况，不计为失败
            self._run(["config", "--global", "--unset", key])
        return TargetResult(True, "Git 代理已清除")


class EnvTarget(ProxyTarget):
    """基于用户环境变量的目标（curl / wget / python / node / global）。"""

    def __init__(self, target_id, name, keys, backend, note=""):
        self.id = target_id
        self.name = name
        self.keys = tuple(keys)
        self.note = note
        self._backend = backend

    def read(self):
        for key in self.keys:
            value = envstore.read_env(self._backend, key)
            if value:
                return value
        return None

    def set(self, url):
        try:
            for key in self.keys:
                envstore.write_env(self._backend, key, url)
        except Exception as exc:
            return TargetResult(False, f"{self.name} 代理设置失败", str(exc))
        return TargetResult(True, f"{self.name} 代理已设置（{len(self.keys)} 个变量）")

    def unset(self):
        try:
            for key in self.keys:
                envstore.unset_env(self._backend, key)
        except Exception as exc:
            return TargetResult(False, f"{self.name} 代理清除失败", str(exc))
        return TargetResult(True, f"{self.name} 代理已清除")


class CompositeTarget(ProxyTarget):
    """组合目标：global 由 curl/wget/node/socks 合并而成。"""

    def __init__(self, target_id, name, children, note=""):
        self.id = target_id
        self.name = name
        self.note = note
        self.children = list(children)

    def read(self):
        for child in self.children:
            value = child.read()
            if value:
                return value
        return None

    def set(self, url):
        results = [child.set(url) for child in self.children]
        ok = sum(1 for r in results if r.ok)
        if ok == 0:
            return TargetResult(False, "全部子目标设置失败",
                                "; ".join(r.detail or r.message for r in results))
        return TargetResult(True, f"已设置 {ok}/{len(results)} 个子目标")

    def unset(self):
        results = [child.unset() for child in self.children]
        ok = sum(1 for r in results if r.ok)
        if ok == 0:
            return TargetResult(False, "全部子目标清除失败",
                                "; ".join(r.detail or r.message for r in results))
        return TargetResult(True, f"已清除 {ok}/{len(results)} 个子目标")


def all_targets(backend=None):
    """构造七类目标。backend 注入点：测试传 FakeBackend。"""
    if backend is None:
        backend = envstore.WinRegistryBackend()
    curl = EnvTarget("curl", "cURL", CURL_KEYS, backend, "http_proxy / https_proxy")
    wget = EnvTarget("wget", "wget", WGET_KEYS, backend, "WGET_PROXY")
    python = EnvTarget("python", "Python", PYTHON_KEYS, backend, "http_proxy / https_proxy")
    node = EnvTarget("node", "Node.js", NODE_KEYS, backend, "HTTP_PROXY / HTTPS_PROXY")
    return [
        GitTarget(),
        curl,
        wget,
        python,
        node,
        CompositeTarget("global", "全局", [curl, wget, node],
                        "curl + wget + node + socks 合并"),
        DockerTarget(),
    ]
