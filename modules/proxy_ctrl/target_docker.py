"""proxy_ctrl/target_docker：Docker daemon.json 的 proxies 节点。

从 targets.py 原子切出，理由是 Docker 分支自带一套 JSON 读写与降级逻辑
（不主动创建文件 / 解析失败跳过 / 需要管理员权限），与 git、环境变量两类
目标没有共用代码。`targets` 模块仍然原样 re-export 本文件的公开名字，
`from .targets import DockerTarget` 等既有调用点不受影响。
"""
import json
import os

from .target_base import ProxyTarget, TargetResult

__all__ = ["DockerTarget", "docker_paths"]


def docker_paths():
    """Docker daemon.json 候选路径（仅已存在的会被使用）。"""
    program_data = os.environ.get("ProgramData") or r"C:\ProgramData"
    return [
        os.path.join(os.path.expanduser("~"), ".docker", "daemon.json"),
        os.path.join(program_data, "docker", "config", "daemon.json"),
    ]


def _read_json(path):
    """读 JSON；返回 (data, error)。文件不存在 data=None, error=None。"""
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def _write_json(path, data):
    """写 JSON（BOM-less，匹配 Docker 期望）。返回 None 或错误串。"""
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        return str(exc)
    return None


class DockerTarget(ProxyTarget):
    """Docker daemon.json 的 proxies 节点。

    只修改**已存在**的 daemon.json —— 不主动创建文件，避免凭空造出
    覆盖用户 Docker 引擎默认行为的配置。解析失败的文件原样跳过。
    """

    id = "docker"
    name = "Docker"
    note = "修改 daemon.json 的 proxies 节点"

    def __init__(self, paths=None):
        self._paths = list(paths) if paths is not None else None

    def paths(self):
        return list(self._paths) if self._paths is not None else docker_paths()

    def existing(self):
        return [p for p in self.paths() if os.path.exists(p)]

    def read(self):
        for path in self.existing():
            data, _err = _read_json(path)
            if not isinstance(data, dict):
                continue
            proxies = data.get("proxies")
            if isinstance(proxies, dict):
                value = proxies.get("http-proxy")
                if value:
                    return str(value)
        return None

    def set(self, url):
        targets = self.existing()
        if not targets:
            return TargetResult(False, "未找到 daemon.json，已跳过")
        skipped, failed = [], []
        for path in targets:
            data, err = _read_json(path)
            if err is not None:
                skipped.append(f"{os.path.basename(path)}: 无法解析({err})")
                continue
            if not isinstance(data, dict):
                skipped.append(f"{os.path.basename(path)}: 顶层不是对象")
                continue
            proxies = data.get("proxies")
            if not isinstance(proxies, dict):
                proxies = {}
            proxies["http-proxy"] = url
            proxies["https-proxy"] = url
            data["proxies"] = proxies
            werr = _write_json(path, data)
            if werr:
                failed.append(f"{os.path.basename(path)}: {werr}")
        note = "; ".join(skipped + failed)
        if len(skipped) + len(failed) == len(targets):
            return TargetResult(False, "Docker 代理设置失败", note)
        ok_n = len(targets) - len(skipped) - len(failed)
        return TargetResult(True, f"Docker 代理已设置（{ok_n} 个文件）", note)

    def unset(self):
        targets = self.existing()
        if not targets:
            return TargetResult(False, "未找到 daemon.json，已跳过")
        skipped, failed = [], []
        for path in targets:
            data, err = _read_json(path)
            if err is not None:
                skipped.append(f"{os.path.basename(path)}: 无法解析({err})")
                continue
            if not isinstance(data, dict):
                skipped.append(f"{os.path.basename(path)}: 顶层不是对象")
                continue
            if "proxies" not in data:
                continue
            data.pop("proxies", None)
            werr = _write_json(path, data)
            if werr:
                failed.append(f"{os.path.basename(path)}: {werr}")
        note = "; ".join(skipped + failed)
        if failed:
            return TargetResult(False, "Docker 代理清除失败（可能需要管理员权限）", note)
        return TargetResult(True, "Docker 代理已清除", note)
