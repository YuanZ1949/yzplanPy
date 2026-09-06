"""RSS 聚合文本/样式辅助：主题色板、关键词解析、HTML 消毒。"""

import html.parser
import re

def _rss_colors():
    """一组主题感知的 RSS 样式色板（明暗两套），供各处列表/按钮/标签统一取色。

    半透明背景保证文字清晰且壁纸可见；无壁纸时也回退为接近全局 QSS 的面板观感。
    """
    try:
        from core.theme import resolve_dark
        dark = resolve_dark("auto")
    except Exception:
        dark = True
    if dark:
        return {
            "dark": True,
            "panel": "rgba(24,24,27,0.74)",
            "panel_soft": "rgba(24,24,27,0.64)",
            "panel_card": "rgba(255,255,255,0.05)",
            "border": "rgba(255,255,255,0.08)",
            "border_strong": "rgba(255,255,255,0.16)",
            # 主强调色
            "accent": "#4aa3ff",
            "accent_hover": "#6eb6ff",
            "accent_pressed": "#2f8ae6",
            "accent_bg": "rgba(74,163,255,0.16)",
            # 文字
            "text": "#e8e8e8",
            "text_secondary": "#9a9a9a",
            "text_faint": "#76767a",
            "title_unread": "#ffffff",
            "title_read": "#8a8a8a",
            # 控件（按钮/输入/下拉）
            "control_bg": "rgba(255,255,255,0.09)",
            "control_bg_hover": "rgba(255,255,255,0.12)",
            "control_border": "rgba(255,255,255,0.10)",
            "control_border_hover": "rgba(255,255,255,0.22)",
            # 标签药丸
            "pill_tag_bg": "rgba(74,163,255,0.18)",
            "pill_tag_fg": "#8fc2ff",
            "pill_torrent_bg": "rgba(255,107,107,0.16)",
            "pill_torrent_fg": "#ff9a9a",
            "pill_article_bg": "rgba(37,205,150,0.16)",
            "pill_article_fg": "#7fe0c0",
            # 徽标/收藏
            "badge_bg": "rgba(74,163,255,0.22)",
            "badge_fg": "#9cc8ff",
            "fav_color": "#ffc107",
            # 列表行
            "row_hover": "rgba(255,255,255,0.05)",
            "row_selected": "rgba(0,120,215,0.30)",
            # 玻璃面板 / 分隔 / 未读圆点
            "header_bg": "rgba(255,255,255,0.05)",
            "header_border": "rgba(255,255,255,0.10)",
            "card_border": "rgba(255,255,255,0.10)",
            "divider": "rgba(255,255,255,0.06)",
            "dot_unread": "#4aa3ff",
            "dot_read": "rgba(255,255,255,0.16)",
            # 分组 / 卡片 / 控件容器 / 选择态（perf 语言对称，T1 新增）
            "group_border": "rgba(255,255,255,0.12)",
            "group_bg": "rgba(255,255,255,0.04)",
            "card_bg": "rgba(255,255,255,0.05)",
            "ctrl_bg": "rgba(255,255,255,0.05)",
            "ctrl_border": "rgba(255,255,255,0.10)",
            "grid_color": "rgba(255,255,255,0.06)",
            "sel_bg": "rgba(0,120,215,0.25)",
            "text_primary": "#e8e8e8",
            "btn_group_bg": "rgba(255,255,255,0.04)",
            "btn_group_border": "rgba(255,255,255,0.08)",
            "menu_bg": "rgba(42,42,44,0.94)",
            "menu_border": "rgba(255,255,255,0.10)",
            "menu_item_hover": "rgba(255,255,255,0.08)",
            "menu_item_selected": "rgba(74,163,255,0.25)",
            # 侧栏彩色徽章（v4 设计）
            "badge": {
                "all": {"bg": "rgba(74,163,255,0.38)", "fg": "#c4deff"},
                "unread": {"bg": "rgba(37,205,150,0.35)", "fg": "#a8f0d8"},
                "fav": {"bg": "rgba(255,193,7,0.32)", "fg": "#ffe88a"},
                "torrent": {"bg": "rgba(255,107,107,0.34)", "fg": "#ffb8b8"},
                "agg": {"bg": "rgba(160,107,255,0.36)", "fg": "#d8c8ff"},
                "feed": {"bg": "rgba(255,255,255,0.28)", "fg": "#e8e8ec"},
            },
        }
    return {
        "dark": False,
        "panel": "rgba(247,247,250,0.90)",
        "panel_soft": "rgba(248,248,251,0.86)",
        "panel_card": "rgba(255,255,255,0.96)",
        "border": "rgba(0,0,0,0.10)",
        "border_strong": "rgba(0,0,0,0.16)",
        "accent": "#1178e0",
        "accent_hover": "#0d5cb8",
        "accent_pressed": "#0a4a96",
        "accent_bg": "rgba(17,120,224,0.10)",
        "text": "#1f1f1f",
        "text_secondary": "#666666",
        "text_faint": "#999999",
        "title_unread": "#111111",
        "title_read": "#9a9a9a",
        "control_bg": "rgba(255,255,255,0.98)",
        "control_bg_hover": "rgba(0,0,0,0.06)",
        "control_border": "rgba(0,0,0,0.10)",
        "control_border_hover": "rgba(0,0,0,0.16)",
        "pill_tag_bg": "#e8f0fe",
        "pill_tag_fg": "#1967d2",
        "pill_torrent_bg": "#fce8e6",
        "pill_torrent_fg": "#c5221f",
        "pill_article_bg": "#e6f4ea",
        "pill_article_fg": "#137333",
        "badge_bg": "#e8f0fe",
        "badge_fg": "#1967d2",
        "fav_color": "#ffb300",
        "row_hover": "rgba(0,120,215,0.06)",
        "row_selected": "rgba(0,120,215,0.16)",
        "header_bg": "rgba(255,255,255,0.72)",
        "header_border": "rgba(0,0,0,0.10)",
        "card_border": "rgba(0,0,0,0.10)",
        "divider": "rgba(0,0,0,0.06)",
        "dot_unread": "#1178e0",
        "dot_read": "rgba(0,0,0,0.16)",
        "group_border": "rgba(0,0,0,0.10)",
        "group_bg": "rgba(0,0,0,0.02)",
        "card_bg": "rgba(255,255,255,0.96)",
        "ctrl_bg": "rgba(255,255,255,0.98)",
        "ctrl_border": "rgba(0,0,0,0.10)",
        "grid_color": "rgba(0,0,0,0.06)",
        "sel_bg": "rgba(0,120,215,0.16)",
        "text_primary": "#1f1f1f",
        "btn_group_bg": "rgba(0,0,0,0.03)",
        "btn_group_border": "rgba(0,0,0,0.08)",
        "menu_bg": "rgba(252,252,252,0.98)",
        "menu_border": "rgba(0,0,0,0.10)",
        "menu_item_hover": "rgba(0,0,0,0.05)",
        "menu_item_selected": "rgba(17,120,224,0.16)",
        "badge": {
            "all": {"bg": "#e8f0fe", "fg": "#1967d2"},
            "unread": {"bg": "#e6f4ea", "fg": "#137333"},
            "fav": {"bg": "#fff6dd", "fg": "#b26a00"},
            "torrent": {"bg": "#fce8e6", "fg": "#c5221f"},
            "agg": {"bg": "#f0eaff", "fg": "#6a3fd8"},
            "feed": {"bg": "rgba(0,0,0,0.06)", "fg": "#5f6368"},
        },
    }


def _rss_panel_colors():
    """兼容旧用法：只返回页面板背景色三项。"""
    c = _rss_colors()
    return {"panel": c["panel"], "panel_soft": c["panel_soft"], "border": c["border"]}


_QF = None


def _qf():
    """按需导入并缓存 qfluentwidgets 组件/图标，避免拖慢模块导入。"""
    global _QF
    if _QF is None:
        from qfluentwidgets import (  # noqa: F401
            CaptionLabel, CheckBox, ComboBox, DropDownPushButton, FluentIcon,
            IconWidget, PrimaryDropDownPushButton, PushButton, PrimaryPushButton,
            PrimaryToolButton, RoundMenu, SearchLineEdit, StrongBodyLabel, ToggleButton,
            ToolButton, TransparentToolButton,
        )
        _QF = dict(
            CaptionLabel=CaptionLabel, CheckBox=CheckBox, ComboBox=ComboBox,
            DropDownPushButton=DropDownPushButton, FluentIcon=FluentIcon,
            IconWidget=IconWidget, PrimaryDropDownPushButton=PrimaryDropDownPushButton,
            PushButton=PushButton, PrimaryPushButton=PrimaryPushButton,
            PrimaryToolButton=PrimaryToolButton,
            RoundMenu=RoundMenu, SearchLineEdit=SearchLineEdit,
            StrongBodyLabel=StrongBodyLabel,
            ToggleButton=ToggleButton, ToolButton=ToolButton,
            TransparentToolButton=TransparentToolButton,
        )
    return _QF


def _parse_keywords(text):
    """把用户输入的关键词文本（逗号/空格/换行分隔）解析为去重后的列表。"""
    parts = []
    for raw in re.split(r"[,，\s]+", text or ""):
        tok = raw.strip()
        if tok and tok not in parts:
            parts.append(tok)
    return parts


# ── 预览 HTML 白名单净化（标准库）──────────────
_ALLOWED_TAGS = {
    "p", "br", "b", "strong", "i", "em", "u", "s", "strike", "sub", "sup",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code", "hr", "div", "span", "table", "thead",
    "tbody", "tr", "th", "td", "caption",
    "a", "img", "figure", "figcaption", "audio", "video", "source",
}
_ALLOWED_ATTRS = {"href", "src", "title", "alt", "width", "height", "colspan", "rowspan", "controls", "poster", "loop", "muted"}
_URL_ATTRS = {"href": "http", "src": "http", "poster": "http"}
# 连同内容一起整体移除的危险/无关标签
_SKIP_TAGS = {
    "script", "style", "iframe", "object", "embed", "form", "input",
    "button", "svg", "math", "link", "meta", "base", "noscript", "template",
}
# HTML 空元素：无内容、无结束标签
_VOID_TAGS = {
    "br", "hr", "img", "source", "input", "meta", "link", "area",
    "base", "col", "wbr", "param", "track", "embed",
}


class _Sanitizer(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._stack = []  # 记录已开放的非 void 标签帧: (kind, tag)

    @staticmethod
    def _clean_attrs(attrs):
        cleaned = []
        for key, val in attrs:
            key = key.lower()
            if key not in _ALLOWED_ATTRS or key.startswith("on"):
                continue
            val = (val or "").strip()
            if key in _URL_ATTRS:
                low = val.lower()
                if not (low.startswith(("http:", "https:", "//", "/")) or low.startswith("data:image/")):
                    continue
            cleaned.append((key, val))
        return "".join(f' {k}="{_Sanitizer._escape_attr(v)}"' for k, v in cleaned)

    @staticmethod
    def _escape_attr(v):
        return (v or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        is_void = tag in _VOID_TAGS
        if tag in _SKIP_TAGS:
            if not is_void:
                self._stack.append(("skip", tag))
            return
        if tag not in _ALLOWED_TAGS:
            if not is_void:
                self._stack.append(("omit", tag))
            return
        if not is_void:
            kind = "a" if tag == "a" else "normal"
            self._stack.append((kind, tag))
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_TAGS or tag not in _ALLOWED_TAGS:
            return
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}/>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _VOID_TAGS or not self._stack:
            return
        kind, t = self._stack.pop()
        if kind == "skip":
            return
        if t == tag and tag in _ALLOWED_TAGS:
            self.out.append(f"</{t}>")

    def handle_data(self, data):
        if any(kind == "skip" for kind, _t in self._stack):
            return
        self.out.append(data)

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")


def _sanitize_html(src):
    """净化不可信的 HTML（RSS 描述/网页内容），仅保留白名单标签与安全属性。"""
    if not src:
        return ""
    p = _Sanitizer()
    try:
        p.feed(src)
        p.close()
    except Exception:
        return ""
    return "".join(p.out)
