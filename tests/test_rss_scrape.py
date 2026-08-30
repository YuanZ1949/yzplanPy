import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.rss_store import (
    RssStore, scrape_html, scrape_page, find_elements, _build_dom,
)
from modules.rss_aggregator import _sanitize_html

NEWS_HTML = (
    "<html><body>"
    '<div class="news-list">'
    '<div class="item" id="a1"><h2 class="t">News One</h2><a href="/news/1">read</a></div>'
    '<div class="item" id="a2"><h2 class="t">News Two</h2><a href="/news/2">read</a></div>'
    '<div class="item" id="a3"><h2 class="t">News Three</h2></div>'
    "</div>"
    '<span class="price">$99</span>'
    "</body></html>"
)


def test_selector_by_tag_class():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, "div.item")
    assert [n.get("id") for n in items] == ["a1", "a2", "a3"]


def test_selector_by_id():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, "#a2")
    assert len(items) == 1
    assert items[0].get("id") == "a2"


def test_selector_attribute():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, 'a[href^="/news"]')
    assert len(items) == 2


def test_selector_descendant():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, "div.item h2.t")
    assert len(items) == 3
    assert items[0].text.strip() == "News One"


def test_selector_comma():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, "span.price, div.item")
    assert len(items) == 4


def test_selector_child():
    html = '<ul class="l"><li>a</li><li>b</li></ul><ul class="m"><li>c</li></ul>'
    dom = _build_dom(html)
    items = find_elements(dom, "ul.l > li")
    assert len(items) == 2
    assert items[0].text.strip() == "a"


def test_scrape_list_mode():
    opts = {
        "mode": "list",
        "selector": "div.item",
        "item": {
            "title": {"sel": "h2.t"},
            "link": {"sel": "a", "attr": "href"},
            "content": {"sel": "h2.t"},
        },
    }
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert len(entries) == 3
    assert entries[0]["title"] == "News One"
    assert entries[0]["link"] == "http://example.com/news/1"
    assert entries[0]["published"]


def test_scrape_single_mode():
    opts = {"mode": "single", "selector": "span.price"}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert len(entries) == 1
    assert entries[0]["title"] == "$99"


def test_scrape_no_match():
    assert scrape_html(NEWS_HTML, {"mode": "list", "selector": "div.missing"}) == []


def test_scrape_dedup_via_ingest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("news", "http://example.com/", "News", feed_type="scrape")
    opts = {
        "mode": "list",
        "selector": "div.item",
        "item": {"title": {"sel": "h2.t"}, "link": {"sel": "a", "attr": "href"}},
    }
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert store.ingest("News", entries) == 3
    assert store.ingest("News", entries) == 0


def test_feed_type_persistence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("mon", "http://example.com/", "Mon", feed_type="scrape",
                   scrape_options={"mode": "single", "selector": "span.price"}, rendered=1)
    feed = store.list_feeds()[0]
    assert feed["feed_type"] == "scrape"
    assert feed["scrape_options"] == '{"mode": "single", "selector": "span.price"}'
    assert feed["rendered"] == 1

    store.update_feed(feed["id"], scrape_options={"mode": "list"})
    feed2 = store.get_feed_by_id(feed["id"])
    assert feed2["scrape_options"] == '{"mode": "list"}'


def test_scrape_page_with_monkeypatched_requests(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import requests

    class FakeResp:
        status_code = 200
        content = NEWS_HTML.encode("utf-8")

        def raise_for_status(self):
            return None

    called = {}

    def fake_get(url, timeout, headers, proxies):
        called["url"] = url
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    opts = {"mode": "list", "selector": "div.item",
            "item": {"title": {"sel": "h2.t"}, "link": {"sel": "a", "attr": "href"}}}
    entries = scrape_page("http://example.com/", opts)
    assert called["url"] == "http://example.com/"
    assert len(entries) == 3


def test_selector_nth_child():
    dom = _build_dom(NEWS_HTML)
    items = find_elements(dom, "div.item:nth-child(2)")
    assert len(items) == 1
    assert items[0].get("id") == "a2"


def test_selector_nth_of_type():
    html = '<div class="s"><p>x</p><p>y</p><span>z</span></div>'
    dom = _build_dom(html)
    items = find_elements(dom, "p:nth-of-type(2)")
    assert len(items) == 1
    assert items[0].text.strip() == "y"


def test_selector_child_star():
    html = '<div class="s"><p>x</p><p>y</p></div>'
    dom = _build_dom(html)
    items = find_elements(dom, "div.s > *")
    assert len(items) == 2


def test_selector_attr_operators():
    html = '<a href="http://x/abc">1</a><a href="mailto:a@b">2</a>'
    dom = _build_dom(html)
    assert len(find_elements(dom, 'a[href^="http"]')) == 1
    assert len(find_elements(dom, 'a[href*="x/"]')) == 1
    assert len(find_elements(dom, 'a[href$="b"]')) == 1


def test_scrape_link_resolution_relative():
    opts = {
        "mode": "list",
        "selector": "a.item",
        "item": {"title": {"text": True}, "link": {"attr": "href"}},
    }
    html = '<div><a class="item" href="/page/1">One</a><a class="item" href="two">Two</a></div>'
    entries = scrape_html(html, opts, "https://site.com/base/")
    assert entries[0]["link"] == "https://site.com/page/1"
    assert entries[1]["link"] == "https://site.com/base/two"


def test_scrape_keyword_like_container_children():
    # 模拟「锁定容器后对其子元素生成多条」
    opts = {
        "mode": "list",
        "selector": "table tr",
        "item": {"title": {"sel": "td:first-of-type"}, "link": {"sel": "a", "attr": "href"}},
    }
    html = (
        "<table><tr><td>A</td><td><a href='/a'>x</a></td></tr>"
        "<tr><td>B</td><td><a href='/b'>y</a></td></tr></table>"
    )
    entries = scrape_html(html, opts, "http://example.com/")
    assert [e["title"] for e in entries] == ["A", "B"]


def test_scrape_max_items():
    opts = {"mode": "list", "selector": "div.item", "max_items": 2}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert len(entries) == 2


def test_scrape_mode_default_list_without_item_spec():
    opts = {"mode": "list", "selector": "div.item"}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert len(entries) == 3
    assert entries[0]["title"]  # 默认取元素文本


def test_scrape_keyword_filter_empty_accepts_all():
    opts = {"mode": "list", "selector": "div.item",
            "item": {"title": {"sel": "h2.t"}}}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert len(entries) == 3


def test_scrape_keyword_filter_any():
    opts = {"mode": "list", "selector": "div.item",
            "item": {"title": {"sel": "h2.t"}},
            "keywords": ["One", "Three"]}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    titles = [e["title"] for e in entries]
    assert "News One" in titles
    assert "News Three" in titles
    assert "News Two" not in titles


def test_scrape_keyword_filter_case_insensitive():
    opts = {"mode": "list", "selector": "div.item",
            "item": {"title": {"sel": "h2.t"}},
            "keywords": ["news one"]}
    entries = scrape_html(NEWS_HTML, opts, "http://example.com/")
    assert [e["title"] for e in entries] == ["News One"]


def test_sanitize_strips_script_and_event_handlers():
    src = '<p onclick="x()">hi <script>alert(1)</script><b>ok</b></p>'
    out = _sanitize_html(src)
    assert "<script" not in out
    assert "onclick" not in out
    assert "alert" not in out
    assert "<b>ok</b>" in out
    assert out.startswith("<p>")


def test_sanitize_strips_javascript_urls_and_iframe():
    src = '<a href="javascript:evil()">x</a><iframe src="evil"></iframe><img src="javascript:x">'
    out = _sanitize_html(src)
    assert "javascript:" not in out
    assert "<iframe" not in out
    assert "evil" not in out


def test_sanitize_strips_style_object_embedded():
    src = '<style>bad</style><object data="x"></object><embed src="y"><p>keep</p>'
    out = _sanitize_html(src)
    assert "<style" not in out and "bad" not in out
    assert "<object" not in out and "<embed" not in out
    assert "<p>keep</p>" in out


def test_sanitize_keeps_allowed_tags_and_http_urls():
    src = '<a href="https://example.com/x">link</a><img src="//cdn/x.png" alt="a"><ul><li>1</li></ul>'
    out = _sanitize_html(src)
    assert "example.com/x" in out
    assert "cdn/x.png" in out
    assert "<ul>" in out and "<li>1</li>" in out


def test_sanitize_empty_input():
    assert _sanitize_html("") == ""
    assert _sanitize_html(None) == ""


def test_auto_link_fallback_to_descendant_anchor():
    opts = {"mode": "list", "selector": "div.item"}
    entries = scrape_html(NEWS_HTML, opts, "https://example.com/")
    # 含 <a> 的元素自动合并链接；无链接元素保持空
    assert entries[0]["link"] == "https://example.com/news/1"
    assert entries[1]["link"] == "https://example.com/news/2"
    assert entries[2]["link"] == ""  # News Three 无 <a href>


def test_auto_link_when_element_itself_is_anchor():
    html = (
        "<html><body>"
        '<a class="story" href="/s/10">Story Ten</a>'
        '<a class="story" href="/s/11">Story Eleven</a>'
        "</body></html>"
    )
    opts = {"mode": "list", "selector": "a.story"}
    entries = scrape_html(html, opts, "https://site.com/")
    assert [e["title"] for e in entries] == ["Story Ten", "Story Eleven"]
    assert [e["link"] for e in entries] == ["https://site.com/s/10", "https://site.com/s/11"]


def test_auto_link_relative_protocol_resolution():
    html = '<a class="x" href="//cdn.example.com/a">A</a>'
    opts = {"mode": "list", "selector": "a.x"}
    entries = scrape_html(html, opts, "https://site.com/page")
    assert entries[0]["link"] == "https://cdn.example.com/a"


def test_auto_link_not_override_explicit_link_spec():
    opts = {
        "mode": "list",
        "selector": "div.item",
        "item": {"link": {"sel": "a", "attr": "href"}},
    }
    entries = scrape_html(NEWS_HTML, opts, "https://example.com/")
    assert entries
    assert entries[0]["link"] == "https://example.com/news/1"
