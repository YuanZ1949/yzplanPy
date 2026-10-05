import importlib


def test_module_info_contract():
    mod = importlib.import_module("modules.right_menu")
    assert mod.MODULE_INFO["id"] == "right_menu"
    assert mod.MODULE_INFO["name"] and mod.MODULE_INFO["description"]
    assert issubclass(mod.Module, __import__("modules.base", fromlist=["ModuleBase"]).ModuleBase)
    assert mod.Module.MODULE_ID == "right_menu"


def test_lazy_export_via_getattr():
    mod = importlib.import_module("modules.right_menu")
    assert mod.Module.MODULE_ID == mod.MODULE_INFO["id"]  # 两次 __getattr__ 均可用
