"""模块注册表：扫描 modules/ 下的模块文件，按 MODULE_INFO 注册。"""
import importlib
import importlib.util
import os
import pkgutil
import traceback

from .base import ModuleBase

_SKIP = {
    "__init__",
    "base",
    "registry",
    "legacy",
    "MyAnime",
    "rss",
    "bulletin",
    "events",
    "gui",
    "monitor",
    "timeline",
}


class ModuleContext:
    """传递给每个模块的应用上下文。"""

    def __init__(self, config, host_window, app):
        self.config = config
        self.host_window = host_window
        self.app = app


class ModuleRegistry:
    def __init__(self, context):
        self.context = context
        self._modules = {}
        self._load_all()

    def _module_files(self):
        import modules as pkg
        files = []
        for info in pkgutil.iter_modules(pkg.__path__, f"{pkg.__name__}."):
            name = info.name.rsplit(".", 1)[-1]
            if name in _SKIP:
                continue
            files.append(name)
        return sorted(files)

    def _load_all(self):
        for modname in self._module_files():
            try:
                mod = importlib.import_module(f"modules.{modname}")
                info = getattr(mod, "MODULE_INFO", None)
                cls = getattr(mod, "Module", None)
                if not info or not cls or not issubclass(cls, ModuleBase):
                    continue
                instance = cls(self.context)
                self._modules[instance.id] = instance
            except Exception:
                print(f"[registry] 加载模块 {modname} 失败:")
                traceback.print_exc()

    def all(self):
        return list(self._modules.values())

    def get(self, module_id):
        return self._modules.get(module_id)

    def is_enabled(self, module_id):
        mod = self.get(module_id)
        if mod is None:
            return False
        default = mod.ENABLED_BY_DEFAULT
        return self.context.config.module_enabled(module_id, default)

    def enabled(self):
        return [m for m in self._modules.values() if self.is_enabled(m.id)]

    def start_enabled(self):
        for mod in self.enabled():
            try:
                mod.start()
            except Exception:
                traceback.print_exc()

    def stop_all(self):
        for mod in self._modules.values():
            try:
                mod.stop()
            except Exception:
                pass