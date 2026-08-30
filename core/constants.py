APP_NAME = "YZplan"
APP_VERSION = "0.1.0"
APP_ID = "yzplan"

import os
import sys

if getattr(sys, "frozen", False):
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    EXE_DIR = os.path.dirname(sys.executable)
    PROJECT_DIR = EXE_DIR
    DATA_DIR = os.path.join(EXE_DIR, "data")
else:
    BUNDLE_DIR = None
    PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(PROJECT_DIR, "data")

CONFIG_PATH = os.path.join(DATA_DIR, "settings.json")
DB_PATH = os.path.join(DATA_DIR, "app.db")
TRANSLATION_DIR = os.path.join(PROJECT_DIR, "translation")
ICON_PATH = os.path.join(BUNDLE_DIR or PROJECT_DIR, "data", "favicon.ico")

DEFAULT_CONFIG = {
    "window": {
        "width": 1280,
        "height": 800,
        "x": None,
        "y": None,
        "start_hidden": False,
    },
    "autostart": False,
    "close_to_tray": True,
    "ui": {
        "theme": "auto",
        "wallpaper": "",
        "acrylic": False,
        "wallpaper_opacity": 0.35,
        "acrylic_blur_radius": 35,
        "acrylic_opacity": 0.7,
    },
    "modules": {},
    "rss": {
        "home_limit": 100000,
        "proxy": "",
        "default_refresh_interval": 1800,
        "retry_count": 3,
        "retry_delay": 5,
        "notification_enabled": True,
        "cleanup_days": 30,
        "fetch_timeout": 15,
        "auto_cleanup": False,
        "min_refresh_interval": 300,
    },
    "home": {
        "layout": {},
        "order": [],
        "background": "#1e1e2e",
        "column_width": 320,
        "gap": 12,
        "margin": 10,
    },
}