"""modules/rss_store slice: lightweight DOM engine (spliced by T13 codebase-reorg)."""
from html.parser import HTMLParser


# ── 页面监控：轻量 HTML DOM + CSS 选择器引擎 ──────────────────────
# 仅依赖标准库 (html.parser)，不依赖 lxml/bs4/Qt，可独立测试。

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class HtmlElement:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.text = ""

    def get(self, name, default=""):
        v = self.attrs.get(name.lower())
        return default if v is None else v


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlElement("#root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        parent = self._stack[-1]
        node = HtmlElement(tag, dict(attrs), parent)
        parent.children.append(node)
        if tag not in _VOID_TAGS and not self._is_void_like(tag):
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        parent = self._stack[-1]
        node = HtmlElement(tag, dict(attrs), parent)
        parent.children.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return
        # 未匹配的结束标签：忽略

    def handle_data(self, data):
        if self._stack:
            self._stack[-1].text += data

    def _is_void_like(self, tag):
        return False


def _build_dom(html):
    builder = _TreeBuilder()
    try:
        builder.feed(html or "")
        builder.close()
    except Exception:
        pass
    return builder.root


def _normalize_text(text):
    import re as _re
    if not text:
        return ""
    return _re.sub(r"\s+", " ", text).strip()


def _inner_html(node):
    return _inner_text(node)


def _inner_text(node):
    parts = [node.text or ""]
    for c in node.children:
        parts.append(_inner_text(c))
    return _normalize_text("".join(parts))


def _walk(node):
    if node is None:
        return
    yield node
    for c in node.children:
        yield from _walk(c)


def _attr_match(node, name, op, value):
    val = node.get(name)
    if op == "exists":
        return val != ""
    val = val or ""
    value = value or ""
    if op == "=":
        return val == value
    if op == "^=":
        return val.startswith(value)
    if op == "$=":
        return val.endswith(value)
    if op == "*=":
        return value in val
    if op == "~=":
        return value in val.split()
    if op == "|=":
        return val == value or val.startswith(value + "-")
    return False


def _sibling_index(node):
    """返回 node 在同级中的下标（0 基）。"""
    if node.parent is None:
        return 0
    return node.parent.children.index(node)


def _sibling_of_type_index(node):
    """返回 node 在同类标签兄弟中的下标（0 基）。"""
    if node.parent is None:
        return 0
    return [c for c in node.parent.children if c.tag == node.tag].index(node)


def _match_simple(node, token):
    """匹配单一选择器片段，如 tag、.class、#id、[attr=val]、*、:nth-child(n)。"""
    tag, cls, ident, attr, pseudos = token
    if tag and tag != "*" and node.tag != tag.lower():
        return False
    for c in cls:
        if c not in node.get("class", "").split():
            return False
    if ident and node.get("id") != ident:
        return False
    for name, op, value in attr:
        if not _attr_match(node, name, op, value):
            return False
    for pname, parg in pseudos:
        if pname == "nth-child":
            if _sibling_index(node) + 1 != parg:
                return False
        elif pname == "nth-of-type":
            if _sibling_of_type_index(node) + 1 != parg:
                return False
        elif pname in ("first-child", "last-child", "first-of-type", "last-of-type"):
            is_first = _sibling_index(node) == 0
            is_last = (node.parent is not None) and _sibling_index(node) == len(node.parent.children) - 1
            is_first_type = _sibling_of_type_index(node) == 0
            is_last_type = (node.parent is not None) and _sibling_of_type_index(node) == len(
                [c for c in node.parent.children if c.tag == node.tag]
            ) - 1
            if pname == "first-child" and not is_first:
                return False
            if pname == "last-child" and not is_last:
                return False
            if pname == "first-of-type" and not is_first_type:
                return False
            if pname == "last-of-type" and not is_last_type:
                return False
    return True


def _parse_simple(token_str):
    """把形如 'div.a#b[href^=x]:nth-child(2)' 解析为 (tag,[classes],id,[attr],[pseudo])"""
    import re as _re
    tag = ""
    classes = []
    ident = ""
    attrs = []
    pseudos = []
    rest = token_str.strip()
    m = _re.match(r"^[\w-]+", rest)
    if m:
        tag = m.group(0)
        rest = rest[m.end():]
    while rest:
        if rest.startswith("."):
            mm = _re.match(r"\.([\w-]+)", rest)
            if mm:
                classes.append(mm.group(1))
                rest = rest[mm.end():]
                continue
        if rest.startswith("#"):
            mm = _re.match(r"#([\w-]+)", rest)
            if mm:
                ident = mm.group(1)
                rest = rest[mm.end():]
                continue
        if rest.startswith(":"):
            mm = _re.match(r":([\w-]+)(?:\((.*?)\))?", rest)
            if mm:
                name = mm.group(1).lower()
                arg = mm.group(2)
                if name == "nth-child" and arg is not None:
                    try:
                        pseudos.append((name, int(arg.strip())))
                    except ValueError:
                        pass
                elif name == "nth-of-type" and arg is not None:
                    try:
                        pseudos.append((name, int(arg.strip())))
                    except ValueError:
                        pass
                elif name in ("first-child", "last-child", "first-of-type", "last-of-type"):
                    pseudos.append((name, None))
                rest = rest[mm.end():]
                continue
        if rest.startswith("["):
            mm = _re.match(r"\[([\w:-]+)([\^$*~|]?=)?(.*?)\]", rest)
            if mm:
                name = mm.group(1).lower()
                op = mm.group(2) or "exists"
                value = mm.group(3).strip().strip("\"'")
                attrs.append((name, op, value))
                rest = rest[mm.end():]
                continue
        break
    return tag, classes, ident, attrs, pseudos


def _split_top(text, sep):
    parts = []
    depth = 0
    cur = ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]
