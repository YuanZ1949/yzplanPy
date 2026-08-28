"""模块基类与协议。"""


class ModuleBase:
    MODULE_ID = ""
    MODULE_NAME = ""
    MODULE_DESCRIPTION = ""
    MODULE_VERSION = "0.1"
    ENABLED_BY_DEFAULT = True

    def __init__(self, context):
        """context: 提供 config / host_window / registry 的应用上下文。"""
        self.context = context
        self._running = False

    @property
    def id(self):
        return self.MODULE_ID

    @property
    def name(self):
        return self.MODULE_NAME

    @property
    def description(self):
        return self.MODULE_DESCRIPTION

    @property
    def running(self):
        return self._running

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def create_home_widget(self, parent):
        """主页组件；无则返回 None。"""
        return None

    def create_settings_widget(self, parent):
        """模块设置面板；无则返回 None。"""
        return None

    def create_page(self, parent):
        """模块独立页面；无则返回 None。"""
        return None