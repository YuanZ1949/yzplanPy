"""RSS 侧边栏 / 聚合 / hash 扫描 相关的数据层与 UI 离屏测试。"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from modules.rss_store import RssStore, extract_btih
from modules import rss_aggregator as m


_MAG_A = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=one"
_MAG_B = "magnet:?xt=urn:btih:" + "b" * 40 + "&dn=two"


@pytest.fixture(autouse=True)
def _rss_page_cleanup():
    yield
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for widget in list(app.allWidgets()):
        if isinstance(widget, m._RssPageWidget):
            widget.close()
            widget.deleteLater()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, 0)


def _make_store(tmp_path):
    return RssStore(str(tmp_path / "s.db"))


class FakeConfig(dict):
    def __init__(self):
        super().__init__()
        self._data = {}

    def get(self, key, default=None):
        dct = {**self._data, **dict(self)}
        return dct.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def unset(self, key):
        self._data.pop(key, None)


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()


class FakeOwner:
    def __init__(self, store):
        self.store = store
        self.context = FakeCtx()
        self._scan_calls = 0
        self._icon_calls = 0

    def scan_hashes(self, limit=200):
        self._scan_calls += 1

    def refresh_favicons(self):
        self._icon_calls += 1

    def refresh_now(self):
        """刷新当前视图（测试替身存根）。"""


def _seed_sidebar(store):
    store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.add_feed("站点B", "https://b.example/rss", tag="tB")
    fid = {f["name"]: f["id"] for f in store.list_feeds()}
    fa, fb = fid["站点A"], fid["站点B"]
    store.update_feed_refresh_time(fa)
    store.update_feed_refresh_time(fb)
    store.ingest("tA", [{"title": "Magnet one", "link": _MAG_A, "published": "2026-01-01", "description": "", "image_url": ""}], feed_id=fa)
    store.ingest("tB", [{"title": "Magnet two", "link": _MAG_A.replace("dn=one", "dn=A2"), "published": "2026-01-02", "description": "", "image_url": ""}], feed_id=fb)
    store.ingest("tB", [{"title": "Magnet B", "link": _MAG_B, "published": "2026-01-03", "description": "", "image_url": ""}], feed_id=fb)
    store.ingest("tA", [{"title": "普通文章", "link": "https://a.example/post/1", "published": "2026-01-04", "description": "内有 python 关键词", "image_url": ""}], feed_id=fa)

    # 手动聚合
    aid = store.add_aggregation("聚合A", agg_type="mixed", feed_ids=[fa])
    store.refresh_aggregation(aid)
    kw = store.add_aggregation("关键词聚合", agg_type="keyword", kw_required=["python"])
    store.refresh_aggregation(kw)
    tor = store.add_aggregation("磁链聚合", agg_type="torrent", feed_ids=[fa, fb])
    store.refresh_aggregation(tor)
    return fa, fb, aid, kw, tor


# ── 数据层：extract_btih ─────────────────────────────────────

def test_extract_btih_magnet():
    h = extract_btih("magnet:?xt=urn:btih:" + "A" * 40 + "&dn=x&tr=udp://t")
    assert h == "a" * 40


def test_extract_btih_plain_40hex():
    assert extract_btih("c" * 40) == "c" * 40


def test_extract_btih_none():
    assert extract_btih("https://example.com/a?b=1") == ""
    assert extract_btih("") == ""


def test_extract_btih_base32():
    # 动漫花园等站点用 32 位 Base32 BTIH，应规范化为 40 位 hex
    assert extract_btih("magnet:?xt=urn:btih:T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C&dn=x") == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"
    assert extract_btih("magnet:?xt=urn:btih:aaaa0" + "B" * 27) == ""
    # 大小写归一（base32 大小写无关）
    assert extract_btih("magnet:?xt=urn:btih:t4hjfgghgeeu7wxtanw27ptp77oq4r3c") == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"
    assert len(extract_btih("magnet:?xt=urn:btih:" + "Q" * 32)) == 40


# ── 数据层：ingest 自动填 hash ───────────────────────────────

def test_ingest_fills_torrent_hash(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "a" * 40


# ── 数据层：recent 过滤 ──────────────────────────────────────

def test_recent_feed_ids_filter(tmp_path):
    store = _make_store(tmp_path)
    fa, fb, *_ = _seed_sidebar(store)
    only_a = store.recent(100, feed_ids=[fa])
    assert all(x["title"] in ("Magnet one", "普通文章") for x in only_a)
    assert "普通文章" in [x["title"] for x in only_a]
    # 精确到订阅源：站点A 不应包含站点B 的条目（哪怕同 tag）
    titles_a = {x["title"] for x in only_a}
    assert "Magnet two" not in titles_a
    assert "Magnet B" not in titles_a
    only_b = store.recent(100, feed_ids=[fb])
    assert {x["title"] for x in only_b} == {"Magnet two", "Magnet B"}


def test_recent_keyword_filter(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    res = store.recent(100, keyword="python")
    assert len(res) == 1
    assert res[0]["title"] == "普通文章"


def test_recent_torrent_hash_filter(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    res = store.recent(100, torrent_hash="a" * 40)
    assert len(res) == 2
    assert all(x["torrent_hash"] == "a" * 40 for x in res)
    res_b = store.recent(100, torrent_hash="b" * 40)
    assert len(res_b) == 1


# ── 数据层：list_sidebar ─────────────────────────────────────

def test_list_sidebar_shape(tmp_path):
    store = _make_store(tmp_path)
    _seed_sidebar(store)
    data = store.list_sidebar()
    assert len(data["feeds"]) == 2
    assert all(set(("id", "name", "tag", "icon", "unread", "created_at", "last_refresh")) <= set(f) for f in data["feeds"])
    aggs = {a["name"]: a for a in data["aggregations"]}
    assert set(aggs) == {"聚合A", "关键词聚合", "磁链聚合"}
    assert aggs["磁链聚合"]["agg_type"] == "torrent"
    # 磁链聚合 count = 3（magnet one/two/B 都命中 torrent 类型）
    assert aggs["磁链聚合"]["count"] == 3


def test_aggregation_keyword_tri_bucket(tmp_path):
    store = _make_store(tmp_path)
    _, _, *_ = _seed_sidebar(store)
    # 必须+禁止
    aid = store.add_aggregation("kw2", agg_type="keyword", kw_required=["python"], kw_forbidden=["helloworld"])
    store.refresh_aggregation(aid)
    assert [x["title"] for x in store.recent(100, agg_id=aid)] == ["普通文章"]
    # 必须不满足 → 空
    aid2 = store.add_aggregation("kw3", agg_type="keyword", kw_required=["不存在词"])
    store.refresh_aggregation(aid2)
    assert store.recent(100, agg_id=aid2) == []


def test_aggregation_torrent_groups(tmp_path):
    store = _make_store(tmp_path)
    _, _, _, _, tor = _seed_sidebar(store)
    groups = store.get_aggregation_torrent_groups(tor)
    by_hash = {g["hash"]: g for g in groups}
    assert "a" * 40 in by_hash and "b" * 40 in by_hash
    assert by_hash["a" * 40]["count"] == 2
    assert by_hash["a" * 40]["feed_count"] == 2
    items = store.get_aggregation_torrent_items(tor, "a" * 40)
    assert len(items) == 2


# ── 数据层：torrent links 缓存 + hash 扫描状态 ────────────────

def test_torrent_links_cache_dedup(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    h = store.recent(10)[0]["hash"]
    store.record_item_torrent_links(h, [_MAG_B, "https://z.example/x.torrent"])
    store.record_item_torrent_links(h, [_MAG_B])
    links = store.get_item_torrent_links(h)
    assert len(links) == 2
    assert _MAG_B in links
    it = store.get_item(h)
    assert it is not None
    assert it["torrent_hash"] == "b" * 40


def test_pending_hash_scan_magnet_only(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="磁力站")
    store.ingest("磁力站", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    store.ingest("磁力站", [{"title": "普通", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}])
    # _MAG_A 自带 btih → 不入待扫；但普通条目所在 tag 含“磁” → magnet_only 仍纳入扫描
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1
    assert pend[0]["link"] == "https://a.example/x"
    store.mark_hash_scan([pend[0]["hash"]], 3)
    assert store.get_pending_hash_scans(10) == []


def test_pending_hash_scan_seedz_tag(tmp_path):
    # 种子 标签与 磁 统一处理：种子源的无 hash 条目也应被 magnet_only 纳入
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_is_torrent(fid, 1)
    store.ingest("种子", [{"title": "无hash", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}], feed_id=fid)
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1
    assert pend[0]["link"] == "https://a.example/x"


def test_pending_hash_scan_is_torrent_feed(tmp_path):
    # 标记为磁力/种子源的订阅源，其无 hash 条目会被 magnet_only 纳入（无需 tag 关键词）
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="普通")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_is_torrent(fid, 1)
    store.ingest("普通", [{"title": "无hash", "link": "https://a.example/x", "published": "2026", "description": "", "image_url": ""}], feed_id=fid)
    pend = store.get_pending_hash_scans(10, magnet_only=True)
    assert len(pend) == 1


def test_ingest_base32_from_enclosure_hash(tmp_path):
    # 条目显式携带 base32 BTIH（RSS enclosure 解析结果）应入库
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M", "link": "https://a.example/detail",
                            "description": "", "image_url": "",
                            "torrent_hash": "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"}], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"


def test_ingest_backfills_existing_hash(tmp_path):
    # 旧条目先前入库无 hash，再次 ingest 同条目（带 hash）应回填 torrent_hash
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    entry = {"title": "M", "link": "https://a.example/x", "description": "", "image_url": ""}
    store.ingest("种子", [entry], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == ""
    entry2 = dict(entry)
    entry2["torrent_hash"] = "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"
    store.ingest("种子", [entry2], feed_id=fid)
    it = store.recent(10)[0]
    assert it["torrent_hash"] == "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"


def test_ingest_same_torrent_hex_and_base32_merge(tmp_path):
    # 同一条目分别以 40 位 hex 与 32 位 base32 入库，规范化后应为同一 torrent_hash（能合并分组）
    store = _make_store(tmp_path)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M1", "link": "https://a.example/1",
                           "torrent_hash": "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}], feed_id=fid)
    store.ingest("种子", [{"title": "M2", "link": "https://a.example/2",
                           "torrent_hash": "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"}], feed_id=fid)
    assert store.recent(100) != []
    torrent_hashes = {it["torrent_hash"] for it in store.recent(100)}
    assert torrent_hashes == {"9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}


# ── 数据层：favicon 读写 ─────────────────────────────────────

def test_feed_icon_roundtrip(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("f", "https://a.example/rss", tag="t")
    fid = store.list_feeds()[0]["id"]
    store.set_feed_icon(fid, "base64:AAAA")
    assert store.get_feed_icon(fid) == "base64:AAAA"
    assert store.feeds_needing_favicon() == []  # state=2 不再抓


# ── UI 离屏：侧边栏 + 页面联动 ────────────────────────────────

def _build_page(tmp_path):
    store = _make_store(tmp_path)
    fa, fb, aid, kw, tor = _seed_sidebar(store)
    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    return store, owner, page


def _sidebar_data(page):
    out = []
    for i in range(page._sidebar.list.count()):
        item = page._sidebar.list.item(i)
        data = item.data(QtCore.Qt.UserRole)
        if data is None:
            widget = page._sidebar.list.itemWidget(item)
            label = widget.text() if isinstance(widget, QtWidgets.QLabel) else ""
            data = {"kind": "group", "name": label}
        out.append(data)
    return out


def test_page_sidebar_build(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    # 当前布局：快捷节点 → 分组标题 → 聚合节点 → 分组标题 → 订阅源节点
    kinds = [d.get("kind") for d in _sidebar_data(page)]
    assert kinds[0] == "all"
    assert kinds.count("unread") == 1
    assert kinds.count("fav") == 1
    assert kinds.count("torrent") == 1
    assert kinds.count("agg") == 3
    assert kinds.count("feed") == 2
    assert kinds.count("group") == 2


def test_page_select_feed_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    fa_id = None
    for d in _sidebar_data(page):
        if d.get("kind") == "feed" and d["name"] == "站点A":
            fa_id = d["feed_id"]
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "feed" and d["feed_id"] == fa_id)
    sb.list.setCurrentRow(row)
    assert sb.current_filter() == {"feed_ids": [fa_id]}
    assert page.item_list.count() == 2  # 站点A：magnet one + 普通文章


def test_page_select_keyword_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "关键词聚合")
    sb.list.setCurrentRow(row)
    f = sb.current_filter()
    assert f.get("agg_id") is not None
    assert page.item_list.count() == 1


def test_page_select_torrent_filters(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    f = sb.current_filter()
    assert f.get("agg_type") == "torrent"
    assert page.item_list.count() == 5  # 2 分组头 + 3 成员条目(magnet one/two/B)
    assert "磁链聚合" in page.lb_total.text()
    assert "2 个分组" in page.lb_total.text()


def test_torrent_group_collapse_expand(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    head_hash = next(iter(page._group_children))
    page._toggle_torrent_group(head_hash)
    heads = page._group_children[head_hash]
    assert page.item_list.isRowHidden(page.item_list.row(heads[0])) is False


def test_sidebar_reload_preserves_selection(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "feed" and d["name"] == "站点A")
    sb.list.setCurrentRow(row)
    page._reload_sidebar()
    cur = sb.current_data()
    assert cur.get("kind") == "feed"
    assert cur.get("name") == "站点A"


def test_btih_migration_base32_to_hex(tmp_path):
    # 既有库中 32 位 base32 hash 在 store 重开时应就地迁移为 40 位 hex
    import sqlite3
    db = str(tmp_path / "s.db")
    store = RssStore(db)
    store.add_feed("源", "https://a.example/rss", tag="种子")
    fid = store.list_feeds()[0]["id"]
    store.ingest("种子", [{"title": "M", "link": "https://a.example/1",
                           "torrent_hash": "9f0e9298c731094fdaf3036dafbe6fffdd0e4762"}], feed_id=fid)
    # 直接往库里塞一条 base32 hash 旧数据
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO items(hash,title,link,published,description,image_url,torrent_hash) "
        "VALUES(?,?,?,?,?,?,?)",
        ("h32", "旧条目 base32", "https://a.example/2", "2026-01-01", "", "",
         "T4HJFGGHGEEU7WXTANW27PTP77OQ4R3C"),
    )
    conn.commit()
    conn.close()
    # 重开触发迁移
    store2 = RssStore(db)
    by_hash = {it["torrent_hash"] for it in store2.recent(100)}
    assert "9f0e9298c731094fdaf3036dafbe6fffdd0e4762" in by_hash
    # 旧的 hex 条目保持不变
    assert "9f0e9298c731094fdaf3036dafbe6fffdd0e4762" in by_hash


def test_refresh_menu_multiselect_run(tmp_path):
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    assert hasattr(sb, "btn_refresh_all")
    assert not hasattr(sb, "btn_scan_magnet")
    owner = page.owner
    base_scan, base_icon = owner._scan_calls, owner._icon_calls
    # 勾选 扫描磁力 + 刷新图标
    sb._refresh_actions["scan"].setChecked(True)
    sb._refresh_actions["icons"].setChecked(True)
    sb._run_selected_refresh()
    assert owner._scan_calls == base_scan + 1
    assert owner._icon_calls == base_icon + 1
    # 执行后清除勾选
    assert sb._refresh_ops["scan"] is False
    assert sb._refresh_ops["icons"] is False


def test_settings_dialog_no_hardcoded_theme(tmp_path):
    _, owner, page = _build_page(tmp_path)
    dlg = m._SettingsDialog(owner, page)
    ss = dlg.styleSheet()
    assert "#2c2c2c" not in ss
    assert "rgba(255,255,255,0.10)" not in ss
    assert "rgba(40,40,40,0.85)" not in ss
    dlg.close()


def test_agg_head_count_at_end_no_newline(tmp_path):
    # 磁链聚合 head 行：计数作为独立徽标放在行末(不换行)，标题可换行且不含计数
    _, _, page = _build_page(tmp_path)
    sb = page._sidebar
    row = next(i for i, d in enumerate(_sidebar_data(page)) if d.get("kind") == "agg" and d["name"] == "磁链聚合")
    sb.list.setCurrentRow(row)
    heads = []
    for r in range(page.item_list.count()):
        it = page.item_list.item(r)
        w = page.item_list.itemWidget(it)
        if isinstance(w, m._HeadRow):
            heads.append(w)
    assert heads, "应存在磁链聚合 head 行"
    for w in heads:
        assert "来源" in w.count_label.text()  # 计数徽标含"来源"文案
        assert w.count_label.text().rstrip().endswith("来源")  # 来源计数在行末
        assert w.count_label.wordWrap() is False  # 计数不换行
        assert "\n" not in w.text()  # 标题文本无换行(交给 word-wrap)
        assert w.title_label.wordWrap() is False  # 标题单行省略，不再换行
        # 单行分组头：任意宽度下高度恒定（≤36 下限），不再随标题长度增高
        assert w.heightForWidth(600) <= 36, f"head row too tall: {w.heightForWidth(600)}"
        assert "来源" not in w.text()  # 计数不应混进标题


def test_fetcher_process_feed_returns_dict_on_success(tmp_path):
    # 回归：抓取成功路径必须返回结果 dict，否则 worker 线程 r.get 崩溃
    store, _, _ = _build_page(tmp_path)
    f = dict(store.list_feeds()[0])
    f.setdefault("feed_type", "rss")
    f.setdefault("scrape_options", "{}")
    f.setdefault("rendered", False)
    f.setdefault("custom_headers", "{}")
    f.setdefault("etag", "")
    f.setdefault("last_modified", "")
    fet = m._Fetcher([f], store, "", 1, 1, 1)

    def fake_fetch(*a, **k):
        return ([{"title": "X", "link": "https://x/1", "description": "", "image_url": ""}], "", "etag1", "")

    orig = m.fetch_feed
    m.fetch_feed = fake_fetch
    try:
        r = fet._process_feed(f)
    finally:
        m.fetch_feed = orig
    assert isinstance(r, dict)
    for key in ("feed_id", "name", "tag", "total", "added", "error"):
        assert key in r


def test_page_status_summary_aliases_sidebar_labels(tmp_path):
    """概览/状态标签已迁到侧边栏刷新按钮上方，页面保持别名引用。"""
    store, _, page = _build_page(tmp_path)
    sb = page._sidebar
    assert page.lb_status is sb.lb_status
    assert page.lb_summary is sb.lb_summary
    # 刷新成功后状态文字落入侧边栏标签
    page.on_refreshed([])
    assert sb.lb_status.text()


# ── 预览模式：默认 WebEngine，仅 rss.web_preview=false 用内置阅读视图 ──

def _find_preview_item_hash(store):
    for x in store.search("普通文章", limit=50):
        if str(x.get("link", "")).startswith("https://a.example/post/1"):
            return x["hash"]
    return None


def test_preview_web_by_default(tmp_path, monkeypatch):
    """未配置 rss.web_preview 时默认在内嵌面板加载原文网页。"""
    store, _, page = _build_page(tmp_path)
    h = _find_preview_item_hash(store)
    assert h
    fake_view = QtWidgets.QWidget()
    fake_view.load = lambda url: None
    called = []

    def fake_make_view(parent):
        called.append(True)
        return fake_view, True

    monkeypatch.setattr(m, "_make_preview_view", fake_make_view)
    page._show_preview_by_hash(h, "https://a.example/post/1")
    assert called, "默认应走 WebEngine 预览路径"
    assert page._preview_stack.currentWidget() is fake_view


def test_preview_reading_view_when_web_preview_off(tmp_path):
    """显式关闭时用内置阅读视图，不创建 WebEngine。"""
    store, owner, page = _build_page(tmp_path)
    owner.context.config.set("rss.web_preview", False)
    h = _find_preview_item_hash(store)
    assert h
    page._show_preview_by_hash(h, "https://a.example/post/1")
    assert page._preview_browser_view is None  # 未创建 WebEngine
    assert page._preview_stack.currentWidget() is page._preview_text_view
    html = page._preview_text_view.toHtml()
    assert "原文链接" in html


# ── T4 行渲染容器化：item 行整除 hover 高亮、磁链分组头容器强调 ──

def test_item_row_container_styling():
    """_make_item_row 产物：容器 objectName=rssItemRow，含 hover 高亮规则。"""
    row_widget, title_btn, chk = m.rows_item._make_item_row(
        None, {"title": "标题", "link": "https://x.example/1", "tags": "",
               "published": "2026-01-02T03:04:05", "read": False, "favorite": False}, None)
    assert row_widget.objectName() == "rssItemRow"
    ss = row_widget.styleSheet()
    assert "rssItemRow:hover" in ss
    assert "background: transparent" in ss
    assert chk is not None and title_btn is not None


def test_item_row_thumbnail_rendering():
    """show_thumbnail=True + image_url → 行内出现 40x40 缩略图；默认关闭则不渲染。"""
    it = {"title": "标题", "link": "https://x.example/1", "tags": "",
          "published": "2026-01-02T03:04:05", "read": False, "favorite": False,
          "image_url": "https://x.example/img.png"}
    row_widget, _, _ = m.rows_item._make_item_row(None, it, None, show_thumbnail=True)
    assert row_widget._thumb is not None
    assert row_widget._thumb.width() == 40 and row_widget._thumb.height() == 40
    # 行高至少容纳缩略图
    assert row_widget.heightForWidth(300) >= 40
    # 默认关闭：不渲染缩略图
    row_widget2, _, _ = m.rows_item._make_item_row(None, it, None)
    assert row_widget2._thumb is None


def test_page_thumbnail_toggle(tmp_path):
    """页面缩略图开关：默认关（配置缺省 False），切换后写回配置并重载列表。"""
    store, owner, page = _build_page(tmp_path)
    assert page.btn_thumb.isChecked() is False
    assert page.btn_thumb.text() == "显示缩略图"
    page.btn_thumb.setChecked(True)
    assert owner.context.config.get("rss.show_thumbnails") is True
    assert page._show_thumbnails is True
    assert page.btn_thumb.text() == "隐藏缩略图"
    page.btn_thumb.setChecked(False)
    assert owner.context.config.get("rss.show_thumbnails") is False


def test_head_row_container_styling():
    """_HeadRow 容器样式：#rssHeadRow 规则落地，count 徽章规则仍分派给 count_label。"""
    head = m._HeadRow()
    head.setText("分组标题")
    head.set_count("3 来源")
    head.setStyleSheet(
        "QWidget#rssHeadRow { background: transparent; }"
        "QWidget#rssHeadRow:hover { background: rgba(255,255,255,0.05); }"
        "QPushButton#rssHeadTitle { color: red; }"
        "QPushButton#rssHeadCount { background: blue; }"
    )
    assert "rssHeadRow:hover" in head.styleSheet()
    assert "background: transparent" in head.styleSheet()
    assert "color: red" in head.title_label.styleSheet()
    assert "background: blue" in head.count_label.styleSheet()


# ── T9 离屏冒烟扩展：toolbar 三区分隔、侧栏按钮组、首页未读徽章 ──

def test_tool_bar_uses_current_compact_controls(tmp_path):
    """当前工具栏使用紧凑连续控件，不再依赖旧版竖向分隔条。"""
    store, owner, page = _build_page(tmp_path)
    tool_bar = page.findChild(QtWidgets.QFrame, "rssToolBar")
    assert tool_bar is not None
    assert page.btn_filter.text() == "筛选"
    assert page.btn_read_ops.text() == "阅读"
    assert page.btn_batch_ops.text() == "批量"
    assert page.search_input.minimumWidth() >= 180


def test_tool_row_callbacks_unchanged(tmp_path):
    """T6 插分隔后各工具栏控件回调仍可正常触发（分隔为纯视觉）。"""
    store, owner, page = _build_page(tmp_path)
    # 触发无异常即可（行为级冒烟）
    page.combo_tag.setCurrentIndex(1)
    page.btn_favorites.click()
    page.btn_unread.click()
    page.chk_select_all.setChecked(True)
    assert page.btn_favorites.isChecked()
    assert page.chk_select_all.isChecked()


def test_sidebar_btn_group_frame_styled(tmp_path):
    """T5: 顶部按钮组置于 QFrame#rss_btn_group，带 btn_group 样式（非空 QSS）。"""
    store, owner, page = _build_page(tmp_path)
    frames = [f for f in page._sidebar.findChildren(QtWidgets.QFrame)
              if f.objectName() == "rss_btn_group"]
    assert frames, "应存在名为 rss_btn_group 的 QFrame"
    assert frames[0].styleSheet(), "btn_group 容器应有样式"


def test_home_widget_unread_badge(tmp_path):
    """T3: 首页未读徽章为药丸样式（含 padding/radius），未读为 0 时隐藏。"""
    store = _make_store(tmp_path)
    owner = FakeOwner(store)
    owner.refresh_now = lambda: None
    home = m.home._RssHomeWidget(owner, None)
    ss = home.lb_unread.styleSheet()
    assert "padding" in ss and "border-radius" in ss
    hidden = home.lb_unread.isHidden()
    text = home.lb_unread.text()
    assert (hidden and text == "") or (not hidden and text.startswith("未读:"))


# ── 侧边栏二级聚合条目：层级展示与打开链路 ──────────────────────

def _seed_parent_child_aggs(store):
    """创建父聚合 + keyword/similarity 两个子聚合，返回 (fa, parent_id, kw_child_id, sim_child_id)。"""
    store.add_feed("站C", "https://c.example/rss", tag="tC")
    fid = {f["name"]: f["id"] for f in store.list_feeds()}["站C"]
    store.ingest("tC", [
        {"title": "AI 趋势报告", "link": "https://c.example/ai", "published": "2026-02-01",
         "description": "关于AI的内容", "image_url": ""},
        {"title": "量子计算入门", "link": "https://c.example/quantum", "published": "2026-02-02",
         "description": "量子计算基础", "image_url": ""},
    ], feed_id=fid)
    parent_id = store.add_aggregation("父聚合", agg_type="mixed", feed_ids=[fid])
    assert parent_id is not None
    store.refresh_aggregation(parent_id)
    kw_child_id = store.add_aggregation("关键词子",
                                         agg_type="keyword",
                                         parent_id=parent_id,
                                         kw_required=["AI"])
    store.refresh_aggregation(kw_child_id)
    sim_child_id = store.add_aggregation("相似子",
                                          agg_type="similarity",
                                          parent_id=parent_id,
                                          similarity_threshold=0.70)
    store.refresh_aggregation(sim_child_id)
    return fid, parent_id, kw_child_id, sim_child_id


def test_sidebar_reload_parent_before_child_indent(tmp_path):
    """reload 后 rows 顺序：父聚合在前、子聚合紧跟且子行带 indent 标记。"""
    store = _make_store(tmp_path)
    _seed_parent_child_aggs(store)
    # 需要再 seed 一些基础内容让 _build_page 正常工作
    store.add_feed("站点A", "https://a.example/rss", tag="tA")
    fid_a = {f["name"]: f["id"] for f in store.list_feeds()}["站点A"]
    store.ingest("tA", [{"title": "普通文", "link": "https://a.example/p", "published": "2026-01-01",
                         "description": "", "image_url": ""}], feed_id=fid_a)

    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    sb = page._sidebar

    agg_rows = []
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg":
            agg_rows.append(d)

    parent_idx = next(i for i, d in enumerate(agg_rows) if d["name"] == "父聚合")
    kw_idx = next(i for i, d in enumerate(agg_rows) if d["name"] == "关键词子")
    sim_idx = next(i for i, d in enumerate(agg_rows) if d["name"] == "相似子")
    assert parent_idx < kw_idx < sim_idx, "父聚合应在子聚合之前"

    # 检查子行的 node widget 有 indent 前缀
    kw_item = None
    sim_item = None
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("name") == "关键词子":
            kw_item = sb.list.item(i)
        if d and d.get("kind") == "agg" and d.get("name") == "相似子":
            sim_item = sb.list.item(i)
    # 子聚合应有 parent_id 字段
    assert kw_item is not None
    assert kw_item.data(QtCore.Qt.UserRole).get("parent_id") != 0
    assert sim_item is not None
    assert sim_item.data(QtCore.Qt.UserRole).get("parent_id") != 0
    # 父聚合 parent_id == 0
    parent_item = None
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("name") == "父聚合":
            parent_item = sb.list.item(i)
    assert parent_item is not None
    assert parent_item.data(QtCore.Qt.UserRole).get("parent_id") == 0
    # 子聚合 node widget 的 name label 应含 "·" 前缀
    kw_widget = sb.list.itemWidget(kw_item)
    assert kw_widget is not None
    from modules.rss_aggregator.sidebar import _SidebarNode
    assert isinstance(kw_widget, _SidebarNode)
    assert "·" in kw_widget.name_lb.text()


def test_sidebar_double_click_child_agg_filter(tmp_path):
    """双击子聚合 → current_filter 返回其 agg_id。"""
    store = _make_store(tmp_path)
    fa = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.ingest("tA", [{"title": "普通文", "link": "https://a.example/p", "published": "2026-01-01",
                         "description": "", "image_url": ""}], feed_id=fa)
    parent_id = store.add_aggregation("父聚合", agg_type="mixed", feed_ids=[fa])
    assert parent_id is not None
    store.refresh_aggregation(parent_id)
    kw_child_id = store.add_aggregation("关键词子", agg_type="keyword",
                                         parent_id=parent_id, kw_required=["python"])
    store.refresh_aggregation(kw_child_id)

    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    sb = page._sidebar

    # 选中子聚合
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("agg_id") == kw_child_id:
            sb.list.setCurrentRow(i)
            break
    f = sb.current_filter()
    assert f.get("agg_id") == kw_child_id
    assert f.get("agg_type") == "keyword"


def test_sidebar_double_click_child_agg_opens(tmp_path):
    """双击子聚合 → _open_aggregation 被调用，传入子 agg_id。"""
    store = _make_store(tmp_path)
    fa = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.ingest("tA", [{"title": "普通文", "link": "https://a.example/p", "published": "2026-01-01",
                         "description": "", "image_url": ""}], feed_id=fa)
    parent_id = store.add_aggregation("父聚合", agg_type="mixed", feed_ids=[fa])
    assert parent_id is not None
    store.refresh_aggregation(parent_id)
    kw_child_id = store.add_aggregation("关键词子", agg_type="keyword",
                                         parent_id=parent_id, kw_required=["python"])
    store.refresh_aggregation(kw_child_id)

    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    sb = page._sidebar

    opened = []
    orig_open = page._open_aggregation
    def fake_open(aid):
        opened.append(aid)
    page._open_aggregation = fake_open

    # 找到子聚合并双击
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("agg_id") == kw_child_id:
            sb.list.itemDoubleClicked.emit(sb.list.item(i))
            break
    assert opened == [kw_child_id]
    page._open_aggregation = orig_open


def test_similarity_agg_uses_own_threshold(tmp_path):
    """_load_similarity_aggregation 使用聚合自身的 similarity_threshold。"""
    store = _make_store(tmp_path)
    fa = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.ingest("tA", [
        {"title": "AI 趋势", "link": "https://a.example/ai", "published": "2026-01-01",
         "description": "", "image_url": ""},
        {"title": "AI 未来", "link": "https://a.example/ai2", "published": "2026-01-02",
         "description": "", "image_url": ""},
    ], feed_id=fa)
    sim_agg_id = store.add_aggregation("相似聚", agg_type="similarity",
                                       feed_ids=[fa], similarity_threshold=0.70)
    store.refresh_aggregation(sim_agg_id)

    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)

    # 替换 _cluster_by_similarity_gen 追踪参数
    captured_thresholds = []
    orig_gen = m.page_similarity._cluster_by_similarity_gen
    def spy_gen(members, threshold):
        captured_thresholds.append(threshold)
        return orig_gen(members, threshold)
    m.page_similarity._cluster_by_similarity_gen = spy_gen

    try:
        page._load_similarity_aggregation(sim_agg_id)
        # 聚类在后台 QThread：等线程结束，再冲刷 clustered 队列信号到主线程
        th = getattr(page, "_sim_thread", None)
        assert th is not None
        assert th.wait(5000), "聚类线程未能在 5s 内完成"
        QtCore.QCoreApplication.processEvents()
    finally:
        m.page_similarity._cluster_by_similarity_gen = orig_gen

    assert len(captured_thresholds) == 1
    assert captured_thresholds[0] == 0.70, "应使用聚合自身的阈值 0.70 而非默认 0.55"


def test_similarity_agg_default_threshold(tmp_path):
    """similarity_threshold 未设置时回退到 SIMILARITY_THRESHOLD 常量。"""
    from modules.rss_aggregator.page_similarity import SIMILARITY_THRESHOLD
    store = _make_store(tmp_path)
    fa = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.ingest("tA", [
        {"title": "文A", "link": "https://a.example/a", "published": "2026-01-01",
         "description": "", "image_url": ""},
    ], feed_id=fa)
    sim_agg_id = store.add_aggregation("相似聚", agg_type="similarity", feed_ids=[fa])
    store.refresh_aggregation(sim_agg_id)

    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)

    captured = []
    orig_gen = m.page_similarity._cluster_by_similarity_gen
    def spy_gen(members, threshold):
        captured.append(threshold)
        return orig_gen(members, threshold)
    m.page_similarity._cluster_by_similarity_gen = spy_gen

    try:
        page._load_similarity_aggregation(sim_agg_id)
        th = getattr(page, "_sim_thread", None)
        assert th is not None
        assert th.wait(5000), "聚类线程未能在 5s 内完成"
        QtCore.QCoreApplication.processEvents()
    finally:
        m.page_similarity._cluster_by_similarity_gen = orig_gen

    assert captured[0] == SIMILARITY_THRESHOLD, "未设阈值时应回退默认常量"


def test_parent_agg_context_menu_has_add_sub(tmp_path, monkeypatch):
    """父聚合右键菜单含「添加二级条目」；子聚合不含。"""
    store = _make_store(tmp_path)
    fa = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    store.ingest("tA", [{"title": "文", "link": "https://a.example/p", "published": "2026",
                         "description": "", "image_url": ""}], feed_id=fa)
    parent_id = store.add_aggregation("父", agg_type="mixed", feed_ids=[fa])
    assert parent_id is not None
    child_id = store.add_aggregation("子", agg_type="keyword", parent_id=parent_id, kw_required=["python"])
    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    sb = page._sidebar

    # 用假 QMenu 拦截 exec（offscreen 下真实 exec 会阻塞等待用户输入）
    created_menus = []

    class FakeMenu(QtCore.QObject):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._actions = []
            created_menus.append(self)

        def addAction(self, text):
            act = QtGui.QAction(text, self)
            self._actions.append(act)
            return act

        def exec(self, *a, **k):
            return None

    monkeypatch.setattr(QtWidgets, "QMenu", FakeMenu)

    # 父聚合 → 菜单含「添加二级条目」
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("agg_id") == parent_id:
            sb._show_context_menu(sb.list.visualItemRect(sb.list.item(i)).center())
            break
    texts = [a.text() for a in created_menus[-1]._actions]
    assert "添加二级条目" in texts
    assert "刷新聚合" in texts and "编辑聚合" in texts and "删除聚合" in texts

    # 子聚合 → 菜单不含「添加二级条目」
    for i in range(sb.list.count()):
        d = sb.list.item(i).data(QtCore.Qt.UserRole)
        if d and d.get("kind") == "agg" and d.get("agg_id") == child_id:
            sb._show_context_menu(sb.list.visualItemRect(sb.list.item(i)).center())
            break
    texts2 = [a.text() for a in created_menus[-1]._actions]
    assert "添加二级条目" not in texts2
    assert "刷新聚合" in texts2 and "编辑聚合" in texts2 and "删除聚合" in texts2


# ── 聚合分页：按分组头分页 + 展开/折叠状态跨页保留 ─────────────────

def _make_agg_group(page, i):
    """构造一个最小分组 dict（含 1 个成员），供 _render_agg_page 渲染。"""
    del page
    return {
        "head_key": "h{}".format(i),
        "title": "分组标题{}".format(i),
        "count_text": "1 来源",
        "members": [{
            "title": "成员{}".format(i),
            "link": "http://e.example/{}".format(i),
            "hash": "item-hash-{}".format(i),
            "tags": "",
            "read": False,
            "favorite": False,
            "published": "2026-01-01",
            "description": "",
            "image_url": "",
        }],
        "head_tooltip": "单击标题=预览该分组",
        "head_data": "__agg_head__h{}".format(i),
        "title_cb": lambda *a, **k: None,
        "open_cb": lambda *a, **k: None,
        "toggle_cb": lambda *a, **k: None,
        "checkbox_cb": lambda *a, **k: None,
    }


def test_agg_pagination_across_pages(tmp_path):
    """聚合按分组头分页：60 组 → 2 页，翻页键可用，展开状态跨页保留。"""
    store = _make_store(tmp_path)
    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    page.show()

    page._agg_groups = [_make_agg_group(page, i) for i in range(60)]
    page._agg_total_items = 60
    page._agg_kind_label = "磁链聚合"
    page._agg_mode = True
    page._agg_page = 0
    page._render_agg_page()

    # 第 1 页：50 分组头 + 50 成员 = 100 行
    assert page.lb_page.text() == "第 1 / 2 页"
    assert page.btn_prev.isEnabled() is False
    assert page.btn_next.isEnabled() is True
    assert page.item_list.count() == 100
    assert "60 个分组" in page.lb_total.text() and "共 60 条" in page.lb_total.text()

    # 展开 h0（状态入 _agg_expanded 集合）
    page._toggle_torrent_group("h0")
    assert "h0" in page._agg_expanded
    assert page._head_buttons["h0"].title_label.text().startswith("▾")

    # 下一页 → 第 2 页（10 分组头 + 10 成员 = 20 行）
    page._next_page()
    assert page.lb_page.text() == "第 2 / 2 页"
    assert page.btn_prev.isEnabled() is True
    assert page.btn_next.isEnabled() is False
    assert page.item_list.count() == 20

    # 翻回第 1 页：h0 展开状态与成员可见性保留
    page._agg_page = 0
    page._render_agg_page()
    assert "h0" in page._agg_expanded
    assert page._head_buttons["h0"].title_label.text().startswith("▾")
    for citem in page._group_children["h0"]:
        assert page.item_list.isRowHidden(page.item_list.row(citem)) is False


# ── 侧栏节点：长名称省略号显示 + tooltip 完整名称 ─────────────────

def test_sidebar_node_elides_long_names():
    """长名称侧栏节点：_ElideLabel 渲染省略，text()/tooltip 保留完整名称。"""
    from modules.rss_aggregator.rows import _ElideLabel
    from modules.rss_aggregator.sidebar import _SidebarNode
    full = "这是一个超长侧栏节点名称用于验证省略号截断显示效果"
    node = _SidebarNode(full, badge_char="◉", count=3267)
    node.setFixedWidth(150)
    node.resize(150, 26)
    node.show()

    assert isinstance(node.name_lb, _ElideLabel)
    assert node.name_lb.text() == full          # API 层完整文本
    assert node.name_lb.toolTip() == full       # 悬浮可见完整名称
    # 完整名称宽度必然超过 150px → 实际渲染必然省略
    mw = node.name_lb.fontMetrics().horizontalAdvance(full)
    assert mw > 150
    elided = node.name_lb.fontMetrics().elidedText(full, QtCore.Qt.ElideRight, 130)
    assert elided != full

    node.close()
    node.deleteLater()


# ── 标题栏迁移：独立窗口把页面工具条六控件搬进标题栏 ─────────────────

def _fake_fluent_title_bar():
    """忠实模拟 FluentTitleBar 布局：hBoxLayout=[icon, title, stretch, vBoxLayout]，
    vBoxLayout 内含 buttonLayout(min/max/close 窗口钮)。"""
    tb = QtWidgets.QWidget()
    tb.hBoxLayout = QtWidgets.QHBoxLayout(tb)
    tb.hBoxLayout.setContentsMargins(0, 0, 0, 0)
    tb.iconLabel = QtWidgets.QLabel("◎", tb)
    tb.titleLabel = QtWidgets.QLabel("RSS 聚合", tb)
    tb.hBoxLayout.addWidget(tb.iconLabel)
    tb.hBoxLayout.addWidget(tb.titleLabel)
    tb.hBoxLayout.addStretch(1)
    tb.vBoxLayout = QtWidgets.QVBoxLayout()
    tb.buttonLayout = QtWidgets.QHBoxLayout()
    tb.buttonLayout.setContentsMargins(0, 0, 0, 0)
    for _ in range(3):  # min / max / close 窗口按钮占位
        tb.buttonLayout.addWidget(QtWidgets.QPushButton("□", tb))
    tb.vBoxLayout.addLayout(tb.buttonLayout)
    tb.hBoxLayout.addLayout(tb.vBoxLayout)
    tb.show()
    return tb


def _hbox_items(lay):
    """返回 hBoxLayout 条目序列：('w',widget) / ('l',layout) / ('space',spacer) / ('stretch',spacer)。"""
    out = []
    for i in range(lay.count()):
        it = lay.itemAt(i)
        w = it.widget()
        if w is not None:
            out.append(("w", w))
        elif it.layout() is not None:
            out.append(("l", it.layout()))
        elif it.spacerItem() is not None:
            sp = it.spacerItem()
            if sp.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding:
                out.append(("stretch", sp))
            else:
                out.append(("space", sp))
    return out


def test_build_title_bar_widgets_migration(tmp_path):
    """_build_title_bar_widgets：六控件插入主 hBoxLayout（title 之后、窗口钮之前）、
    移除 Expanding stretch、搜索框自适应、8px 间隔、隐藏 tool_bar、按钮文本收短。"""
    store = _make_store(tmp_path)
    owner = FakeOwner(store)
    page = m._RssPageWidget(owner, None)
    page.show()
    tb = _fake_fluent_title_bar()

    page._build_title_bar_widgets(tb)

    assert page._title_bar_migrated is True
    assert page.tool_bar.isHidden() is True and page.tool_bar.isVisible() is False
    assert page.btn_thumb.text() == "缩略图"
    # 布局条目：[icon][title][12px][search][8px][date][8px][filter][8px][read]
    #           [8px][batch][8px][thumb][12px][vBox]
    items = _hbox_items(tb.hBoxLayout)
    kinds = [k for k, _ in items]
    assert "stretch" not in kinds  # Expanding stretch 已被移除
    assert kinds[:2] == ["w", "w"]
    assert kinds[-1] == "l"
    assert kinds[2:-1] == ["space"] + ["w", "space"] * 5 + ["w"] + ["space"]
    # 间隔尺寸：组缘 12px、组内 8px
    spaces = [it.sizeHint().width() for k, it in items if k == "space"]
    assert spaces[0] == 12 and spaces[-1] == 12
    assert all(s == 8 for s in spaces[1:-1])
    # 控件插入顺序与身份
    ws = [w for k, w in items if k == "w"]
    assert ws[:2] == [tb.iconLabel, tb.titleLabel]
    assert ws[2] is page._search_wg
    assert [page.btn_date_filter, page.btn_filter, page.btn_read_ops,
            page.btn_batch_ops, page.btn_thumb] == ws[3:]
    # vBoxLayout（含窗口钮）仍在最右
    assert items[-1][1] is tb.vBoxLayout
    # 窗口按钮组垂直居中与左侧控件一致
    assert tb.buttonLayout.alignment() & QtCore.Qt.AlignCenter
    # 控件已 REPARENT：_search_wg 及其子控件
    assert page._search_wg.parent() is tb
    assert page.search_input.parent() is page._search_wg
    assert page.combo_search_field.parent() is page._search_wg
    for b in (page.btn_date_filter, page.btn_filter, page.btn_read_ops,
              page.btn_batch_ops, page.btn_thumb):
        assert b.parent() is tb
    # 搜索框横向 Expanding 吸收多余宽度
    assert page.search_input.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding
    # 尺寸收紧
    assert page.search_input.minimumWidth() == 150
    assert page.combo_search_field.minimumWidth() == 44
    assert page.combo_search_field.maximumWidth() == 44
    # —— 风格统一：清除工具条弹片 QSS → Fluent 默认外观 + 全部 30px 高（留呼吸空间）——
    assert page.btn_filter.styleSheet() == ""
    assert page.btn_read_ops.styleSheet() == ""
    for b in (page.btn_date_filter, page.btn_filter, page.btn_read_ops,
              page.btn_batch_ops, page.btn_thumb):
        assert b.minimumHeight() == 30 and b.maximumHeight() == 30
    assert page.search_input.minimumHeight() == 30 and page.search_input.maximumHeight() == 30
    assert page.combo_search_field.minimumHeight() == 30
    # 缩略图按钮已换为 Fluent PushButton（checkable 保留，主题随动）
    from qfluentwidgets import PushButton
    assert isinstance(page.btn_thumb, PushButton)
    assert page.btn_thumb.isCheckable() and page.btn_thumb.isChecked() is False
    # 搜索框 QFrame 去"盒子"感：背景透明
    assert "transparent" in page._search_wg.styleSheet()
    # 幂等：再次调用不重复搬移
    cnt = tb.hBoxLayout.count()
    page._build_title_bar_widgets(tb)
    assert tb.hBoxLayout.count() == cnt

    tb.close()
    tb.deleteLater()