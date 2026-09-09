"""SettingsTab 配置读写：回填控件状态并接线（主题/壁纸/毛玻璃/自启/托盘）。"""
import os
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .log_ops import SettingsTab

class SettingsTab(SettingsTab):  # type: ignore[reportGeneralTypeIssues]

    def _load(self):
        import sys
        cfg = self.context.config

        if sys.platform == "win32":
            from core.autostart import autostart_enabled
            self.cb_autostart.setChecked(autostart_enabled())
            self.cb_autostart.checkedChanged.connect(self._on_autostart)
        else:
            self.cb_autostart.setEnabled(False)

        theme = cfg.get("ui.theme", "auto")
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme:
                self.theme_combo.setCurrentIndex(i)
                break
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        wp = cfg.get("ui.wallpaper", "")
        self.lb_wp_path.setText(os.path.basename(wp) if wp else "未设置")
        self.lb_wp_path.setToolTip(wp)

        self.sw_acrylic.setChecked(cfg.get("ui.acrylic", False))
        self.sw_acrylic.checkedChanged.connect(self._on_acrylic_changed)

        opacity = int(cfg.get("ui.wallpaper_opacity", 0.35) * 100)
        self.slider_opacity.setValue(opacity)
        self.lb_opacity_val.setText(f"{opacity}%")
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)

        blur = int(cfg.get("ui.acrylic_blur_radius", 35))
        self.slider_blur.setValue(blur)
        self.lb_blur_val.setText(f"{blur}px")
        self.slider_blur.valueChanged.connect(self._on_blur_changed)

        glass = int(cfg.get("ui.acrylic_opacity", 0.7) * 100)
        self.slider_glass.setValue(glass)
        self.lb_glass_val.setText(f"{glass}%")
        self.slider_glass.valueChanged.connect(self._on_glass_changed)

        self.cb_close_tray.setChecked(cfg.get("close_to_tray", True))
        self.cb_start_hidden.setChecked(cfg.get("window.start_hidden", False))
        self.cb_close_tray.checkedChanged.connect(self._on_close_tray_changed)
        self.cb_start_hidden.checkedChanged.connect(lambda b: cfg.set("window.start_hidden", b))

    def _on_theme_changed(self, index):
        mode = self.theme_combo.itemData(index)
        if not mode:
            return
        self.context.config.set("ui.theme", mode)
        from core.theme import apply_app_theme, apply_global_stylesheet, resolve_dark
        dark = apply_app_theme(mode)
        apply_global_stylesheet(self.context.config.get("ui.acrylic", False), dark=dark)

    def _browse_wallpaper(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self.widget, "选择壁纸图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)",
        )
        if path:
            self.context.config.set("ui.wallpaper", path)
            self.lb_wp_path.setText(os.path.basename(path))
            self.lb_wp_path.setToolTip(path)
            self._apply_wallpaper()

    def _clear_wallpaper(self):
        self.context.config.set("ui.wallpaper", "")
        self.lb_wp_path.setText("未设置")
        self.lb_wp_path.setToolTip("")
        self._apply_wallpaper()

    def _on_acrylic_changed(self, on):
        self.context.config.set("ui.acrylic", on)
        from core.theme import apply_global_stylesheet
        apply_global_stylesheet(on)
        self._apply_wallpaper()

    def _on_opacity_changed(self, val):
        self.lb_opacity_val.setText(f"{val}%")
        self.context.config.set("ui.wallpaper_opacity", val / 100.0)
        self._apply_wallpaper()

    def _on_blur_changed(self, val):
        self.lb_blur_val.setText(f"{val}px")
        self.context.config.set("ui.acrylic_blur_radius", val)
        self._apply_wallpaper()

    def _on_glass_changed(self, val):
        self.lb_glass_val.setText(f"{val}%")
        self.context.config.set("ui.acrylic_opacity", val / 100.0)
        self._apply_wallpaper()

    def _apply_wallpaper(self):
        mw = getattr(self.context, "host_window", None)
        if mw and hasattr(mw, "apply_wallpaper"):
            mw.apply_wallpaper()

    def _on_autostart(self, enabled):
        from core.autostart import set_autostart
        set_autostart(enabled)

    def _on_close_tray_changed(self, on):
        self.context.config.set("close_to_tray", on)
        mw = getattr(self.context, "host_window", None)
        if mw:
            mw.close_to_tray = on
