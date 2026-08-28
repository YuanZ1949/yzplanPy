"""JSON 配置读写：程序设置、模块开关、主页布局。"""
import json
import os

from .constants import CONFIG_PATH, DEFAULT_CONFIG


class AppConfig:
    def __init__(self, path=CONFIG_PATH, defaults=None):
        self.path = path
        self.defaults = defaults or DEFAULT_CONFIG
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                merged = dict(self.defaults)
                merged.update(raw)
                return merged
            except (OSError, ValueError):
                return dict(self.defaults)
        return self._clone_defaults()

    def _clone_defaults(self):
        import copy
        return copy.deepcopy(self.defaults)

    def get(self, key, default=None):
        cur = self.data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self.data
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            import sys
            print(f"[YZplan] config save failed: {e}", file=sys.stderr)

    def module_setting(self, module_id, key, default=None):
        mod = self.data["modules"].get(module_id, {})
        cfg = mod.get("config", {})
        return cfg.get(key, default)

    def module_enabled(self, module_id, default=True):
        mod = self.data["modules"].get(module_id)
        if mod is None:
            return default
        return bool(mod.get("enabled", default))

    def set_module_enabled(self, module_id, enabled):
        mod = self.data["modules"].setdefault(module_id, {})
        mod["enabled"] = bool(enabled)
        self.save()

    def set_module_config(self, module_id, cfg):
        mod = self.data["modules"].setdefault(module_id, {})
        existing = mod.setdefault("config", {})
        existing.update(cfg)
        self.save()