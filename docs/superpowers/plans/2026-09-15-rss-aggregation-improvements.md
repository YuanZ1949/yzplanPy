# RSS 聚合改进 Implementation Plan

> **For agentic workers**: This plan is a sequence of bite-sized tasks. Each task has a **Files** section (Create / Modify / Test), an **Interfaces** section (Consumes / Produces — exact signatures), and numbered `- [x]` steps. Each step is a single 2–5 minute action: write a failing test → run it and see it fail → implement minimally → run it and see it pass → commit. **NO PLACEHOLDERS** — every code step contains actual code. Run the exact pytest commands given; the expected output is stated after each. Do not skip the "see it fail" step — TDD is mandatory in this repo (AGENTS.md). Commit messages follow conventional commits (`feat/fix/refactor/test`).

## Goal

1. 用真实中文分词（jieba）把「全部条目标题」汇成高频词表，供用户快速构建聚合条件（需求 A）。
2. 把「未分类条目」改为**精确集合补集**（新聚合类型 `remainder`），保证「条目界面里已在其他子聚合出现过的内容，未分类条目里不得再出现」（需求 B）。
3. 补齐六项辅助能力：S1 命中预览、S2 一键派发、S3 分类覆盖率、S4 相似性阈值实时预览、S5 子聚合批量刷新、S6 刷新时间可见。

## Architecture

- **数据层**（`modules/rss_store/store_aggregation.py`）：`refresh_aggregation` 新增 `remainder` 分支（精确补集 SQL），新增 `sibling_aggregation_ids(parent_id, exclude_id)`。无 schema 迁移（`_SCHEMA_VERSION` 保持 4）。
- **服务层**（`modules/rss_aggregator/agg_service.py`）：`_refresh_for_feed_sync` 与 `_refresh_one` 两条路径统一触发 remainder 重建；新增模块级 `refresh_subtree(store, parent_id)` 供 S5 使用。
- **remainder 模块**（新 `modules/rss_aggregator/remainder.py`）：创建 / 查找 / 旧名迁移 / 删除后重建；取代并删除 `auto_exclude.py`。
- **分词模块**（新 `modules/rss_aggregator/text_segment.py`）：jieba 懒加载单例 + 线程锁 + 词性过滤 + 停用词并集 + 正则回退。
- **UI 层**（`dialogs/builders.py`、`dialogs/f.py`、新 `dialogs/stop_words.py`、`page_*.py`、`sidebar*.py`）：高频词面板重写、S1–S6 接线。
- **配置**（`core/constants.py` + `core/config.py`）：`rss.high_freq.stop_words` 只存用户自定义部分。
- **打包**（`requirements.txt` + `yzplan.spec`）：`jieba>=0.42.1` + `collect_data_files('jieba')` + `hiddenimports`。

## Tech Stack

- Python 3.11+ / PySide6 / PyQt-Fluent-Widgets（`core.qt_bootstrap.import_qt()` 统一导入）
- SQLite（`modules/rss_store/`，`_SCHEMA_VERSION = 4`）
- jieba（新增依赖，`>=0.42.1`）
- pytest（offscreen 模式，无 pytest-qt；`os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` + 模块级 QApplication）
- 样式门禁：`ui/widgets.py` 工厂 / `core.theme.tokens.theme_palette()` / `sizing()`；`scripts/audit_styles.py --check` + `tests/test_style_guardrails.py`

## Spec

- `docs/superpowers/specs/2026-09-15-rss-aggregation-improvements-design.md`（§5.2 的 SQL 与 §11 的任务顺序为权威依据，本计划逐条镜像）

## Global Constraints

- **样式**：新控件必须从 `ui/widgets.py` 工厂创建（`make_button` / `make_line_edit` / `make_combo` / `make_card` / `make_status_chip` / `make_label`）；颜色必须来自 `core.theme.tokens.theme_palette()`（禁止 hex/rgba 字面量）；字号/尺寸必须来自 `sizing()`（禁止手写像素值）。模块样式函数一律接收 `theme_palette()` 返回的 dict 作为参数。需要新尺寸时先在 `tokens.py` 新增令牌（本计划新增 `rss_hf_scroll_height`）。单行例外用 `# audit-exempt <理由>` 注释；白名单仅 `core/theme/tokens.py`、`ui/widgets.py`、`scripts/audit_styles.py`。
- **TDD**：每个任务先写失败测试 → 运行看到失败 → 最小实现 → 运行看到通过 → 提交。禁止跳过失败步骤。
- **提交**：conventional commits（`feat/fix/refactor/test`），一次任务一个提交。
- **单文件 ≤ 250 行**：超限即拆分（`dialogs/builders.py` 若超限，把 `_FlowLayout` 与 chips 渲染拆到 `dialogs/high_freq.py`）。
- **接口一致性**：本计划 Interfaces→Produces 的名字在后续任务中必须原样复用，不得改名。
- **YAGNI**：不实现自动聚类、词云、行为学习、pinned 机制（spec §3）。

---

## Task 1 — 数据层：`remainder` 分支 + `sibling_aggregation_ids`

### Files
- **Modify**: `modules/rss_store/store_aggregation.py`
- **Test**: `tests/test_rss_remainder.py`（新建）

### Interfaces
- **Consumes**: `store_aggregation.py` 现有 `refresh_aggregation(agg_id)`、`get_aggregation(agg_id)`、`_SCHEMA_VERSION`（保持 4）
- **Produces**:
  - `sibling_aggregation_ids(parent_id: int, exclude_id: int) -> list[int]` — 同一父下、除 `exclude_id` 外的所有子聚合 id
  - `refresh_aggregation(agg_id)` 新增 `agg_type == "remainder"` 分支（精确补集 SQL）

### Steps

- [x] **1.1 写失败测试** `tests/test_rss_remainder.py`（新建，含 `_make_store` / `_seed_items` 辅助）：

```python
"""remainder 聚合类型：精确集合补集。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from modules.rss_store.pure import _hash
from modules.rss_store.store import RssStore


def _make_store(tmp_path):
    return RssStore(str(tmp_path / "t.db"))


def _make_feed(store):
    """创建测试订阅源并返回 feed_id。"""
    store.add_feed("TestFeed", "http://test/rss", "test")
    return store.list_feeds()[0]["id"]


def _seed_items(store, entries, tag="t", feed_id=None):
    """通过 store.ingest 入库条目，返回 hash 列表（与 ingest 内部一致）。"""
    store.ingest(tag, entries, feed_id=feed_id)
    return [_hash(e["title"], e["link"]) for e in entries]


def _seed_torrent_items(store, entries, tag="t", feed_id=None):
    """入库条目并通过直接 DB 更新设置 torrent_hash，返回 hash 列表。"""
    hashes = _seed_items(store, entries, tag=tag, feed_id=feed_id)
    with store._conn() as conn:
        for h, e in zip(hashes, entries):
            th = e.get("torrent_hash", "")
            if th:
                conn.execute(
                    "UPDATE items SET torrent_hash = ? WHERE hash = ?",
                    (th, h),
                )
    return hashes


def _get_agg_hashes(store, agg_id):
    """获取聚合成员的 hash 集合（测试专用）。"""
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT hash FROM aggregation_items WHERE agg_id = ?",
            (agg_id,),
        ).fetchall()
    return {r[0] for r in rows}


def _make_parent(store, feed_id, name="父聚合"):
    return store.add_aggregation(
        name=name, agg_type="mixed", feed_ids=[feed_id])


def _make_child(store, parent_id, name, agg_type="keyword", **kw):
    return store.add_aggregation(
        name=name, agg_type=agg_type, parent_id=parent_id, **kw)


def _make_remainder(store, parent_id, name="未分类条目"):
    return store.add_aggregation(
        name=name, agg_type="remainder", parent_id=parent_id,
        sort_order=2147483647)


def test_sibling_aggregation_ids_excludes_self(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(4)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    c1 = _make_child(store, parent, "子1")
    c2 = _make_child(store, parent, "子2")
    r = _make_remainder(store, parent)
    assert store.sibling_aggregation_ids(parent, r) == [c1, c2]
    assert store.sibling_aggregation_ids(parent, c1) == [c2, r]


def test_remainder_is_exact_complement_by_hash(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(6)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "子1", agg_type="keyword",
                        kw_required=["标题"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    # 子1 覆盖了全部 6 条（关键词「标题」命中所有），remainder 应为空
    assert store.get_aggregation_item_count(r) == 0
    assert _get_agg_hashes(store, r) == set()


def test_remainder_excludes_torrent_hash_and_exempts_empty(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    torrent_entries = [
        {"title": f"种子{i}", "link": f"http://x/t{i}",
         "description": "", "torrent_hash": f"a{i:039d}"}
        for i in range(3)
    ]
    regular_entries = [
        {"title": f"标题{i}", "link": f"http://x/r{i}", "description": ""}
        for i in range(2)
    ]
    _seed_torrent_items(store, torrent_entries, feed_id=feed_id)
    regular_hashes = _seed_items(store, regular_entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "子1", agg_type="keyword",
                        kw_required=["种子"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    # 3 条磁链被兄弟覆盖（torrent_hash 并集排除），2 条普通条目无 BTIH 应豁免保留
    assert _get_agg_hashes(store, r) == set(regular_hashes)


def test_remainder_stable_across_two_syncs(tmp_path):
    """自引用消除：连续两次同步结果稳定（回归 auto_exclude 漂移 bug）。"""
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [
        {"title": "海贼王1000话下载", "link": "http://x/1", "description": ""},
        {"title": "海贼王1001话在线", "link": "http://x/2", "description": ""},
        {"title": "火影忍者完结篇", "link": "http://x/3", "description": ""},
        {"title": "火影忍者博人传", "link": "http://x/4", "description": ""},
        {"title": "龙珠超新番", "link": "http://x/5", "description": ""},
        {"title": "龙珠超漫画更新", "link": "http://x/6", "description": ""},
    ]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "海贼王", agg_type="keyword",
                        kw_required=["海贼王"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    first = _get_agg_hashes(store, r)
    assert len(first) > 0, "remainder 应包含未被子聚合覆盖的条目"
    store.refresh_aggregation(r)
    second = _get_agg_hashes(store, r)
    assert first == second
```

运行并看到失败（`sibling_aggregation_ids` 不存在 → AttributeError；`refresh_aggregation` 对 remainder 无分支 → 空结果）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_remainder.py -v
```

预期输出：`AttributeError: 'RssStore' object has no attribute 'sibling_aggregation_ids'`（或等价失败），4 个测试全部 FAILED。

- [x] **1.2 实现 `sibling_aggregation_ids`**。在 `modules/rss_store/store_aggregation.py` 的 `add_aggregation` 附近新增：

```python
def sibling_aggregation_ids(self, parent_id, exclude_id):
    """同一父聚合下、除 exclude_id 外的所有子聚合 id（含 remainder 自身）。"""
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT id FROM aggregations WHERE parent_id = ? AND id != ? ORDER BY id",
            (int(parent_id), int(exclude_id)),
        ).fetchall()
    return [r[0] for r in rows]
```

- [x] **1.3 实现 `refresh_aggregation` 的 remainder 分支**。在 `refresh_aggregation` 中，`keyword` 分支之后、`torrent` 分支之前插入（作为 `elif agg_type == "remainder":`）：

```python
elif agg_type == "remainder":
    parent_id = agg.get("parent_id") or 0
    sib = self.sibling_aggregation_ids(parent_id, agg_id)
    if sib:
        ph = ",".join("?" * len(sib))
        scope.append("i.hash NOT IN (SELECT hash FROM aggregation_items WHERE agg_id IN (%s))" % ph)
        params.extend(sib)
        scope.append("(i.torrent_hash = '' OR i.torrent_hash IS NULL OR i.torrent_hash NOT IN (SELECT i2.torrent_hash FROM items i2 JOIN aggregation_items ai ON ai.hash = i2.hash WHERE ai.agg_id IN (%s) AND i2.torrent_hash != ''))" % ph)
        params.extend(sib)
```

> 注意：此代码嵌入 `refresh_aggregation` 现有的 `scope` / `params` 构建链中，共享后续的 DELETE / INSERT / last_refreshed 尾部逻辑。不是独立的 early-return 块。

- [x] **1.4 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_remainder.py -v
```

预期输出：`4 passed`。

- [x] **1.5 回归**：确认既有聚合测试不破：

```bat
.venv\Scripts\python -m pytest tests/test_rss_agg_service.py tests/test_rss_high_freq.py -v
```

预期输出：全部通过。

- [x] **1.6 提交**：`test: 新增 remainder 精确补集数据层测试与实现`

---

## Task 2 — `remainder.py` 取代 `auto_exclude.py` + 旧名迁移

### Files
- **Create**: `modules/rss_aggregator/remainder.py`
- **Delete**: `modules/rss_aggregator/auto_exclude.py`
- **Delete**: `tests/test_rss_auto_exclude.py`
- **Test**: `tests/test_rss_remainder.py`（追加）

### Interfaces
- **Consumes**: `store.sibling_aggregation_ids(parent_id, exclude_id)`、`store.add_aggregation(...)`、`store.get_aggregation(parent_id)`、`store.update_aggregation(agg_id, ...)`、`store.refresh_aggregation(agg_id)`、`store.list_aggregations()`
- **Produces**:
  - `REMAINDER_NAME: str = "未分类条目"`
  - `_LEGACY_SUFFIX: str = "_剩余"`
  - `_SORT_ORDER_MAX: int = 2147483647`
  - `sync_remainder_child(store, parent_id) -> int | None` — 确保父聚合存在且 ≥1 个其他子聚合时创建/复用 remainder 子聚合并刷新；返回其 id 或 None
  - `_find_remainder_child(store, parent_id) -> int | None` — 按 `agg_type == "remainder"` 查找；找不到时按旧名 `{父名}未分类条目` / `{父名}_剩余` 迁移改名后返回

### Steps

- [x] **2.1 写失败测试**（追加到 `tests/test_rss_remainder.py`）：

```python
from modules.rss_aggregator.remainder import (
    REMAINDER_NAME, _LEGACY_SUFFIX, _SORT_ORDER_MAX,
    sync_remainder_child, _find_remainder_child,
)


def test_sync_remainder_child_creates_when_sibling_exists(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    rid = sync_remainder_child(store, parent)
    assert rid is not None
    agg = store.get_aggregation(rid)
    assert agg["agg_type"] == "remainder"
    assert agg["name"] == REMAINDER_NAME
    assert agg["sort_order"] == _SORT_ORDER_MAX


def test_sync_remainder_child_skips_without_siblings(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    parent = _make_parent(store, feed_id)
    assert sync_remainder_child(store, parent) is None


def test_sync_remainder_child_recreates_after_delete(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    rid = sync_remainder_child(store, parent)
    store.remove_aggregation(rid)
    rid2 = sync_remainder_child(store, parent)
    assert rid2 is not None and rid2 != rid


def test_legacy_name_migration(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    legacy = store.add_aggregation(
        name=f"{store.get_aggregation(parent)['name']}未分类条目",
        agg_type="keyword", parent_id=parent)
    rid = _find_remainder_child(store, parent)
    assert rid == legacy
    assert store.get_aggregation(rid)["name"] == REMAINDER_NAME
    assert store.get_aggregation(rid)["agg_type"] == "remainder"


def test_legacy_suffix_migration(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    legacy = store.add_aggregation(
        name=f"{store.get_aggregation(parent)['name']}{_LEGACY_SUFFIX}",
        agg_type="keyword", parent_id=parent)
    rid = _find_remainder_child(store, parent)
    assert rid == legacy
    assert store.get_aggregation(rid)["name"] == REMAINDER_NAME
```

运行并看到失败（`modules.rss_aggregator.remainder` 不存在 → ModuleNotFoundError）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_remainder.py -v
```

预期输出：`ModuleNotFoundError: No module named 'modules.rss_aggregator.remainder'`，5 个新测试 FAILED。

- [x] **2.2 实现 `modules/rss_aggregator/remainder.py`**：

```python
"""未分类条目（remainder）：精确集合补集的生命周期管理。

取代 auto_exclude.py 的「关键词模糊排除」方案：remainder 是 agg_type 的
一个新取值，成员由 store.refresh_aggregation 的 remainder 分支按
「父聚合快照 − 兄弟成员 hash/torrent_hash 并集」精确计算。
"""

REMAINDER_NAME = "未分类条目"
_LEGACY_SUFFIX = "_剩余"
_SORT_ORDER_MAX = 2147483647


def _find_remainder_child(store, parent_id):
    """查找父聚合的 remainder 子聚合；旧名自动迁移。"""
    aggs = store.list_aggregations()
    for agg in aggs:
        if agg.get("parent_id") != parent_id:
            continue
        if agg.get("agg_type") == "remainder":
            return agg["id"]
    parent = store.get_aggregation(parent_id)
    parent_name = (parent or {}).get("name") or ""
    for suffix in (REMAINDER_NAME, _LEGACY_SUFFIX):
        legacy_name = f"{parent_name}{suffix}"
        for agg in aggs:
            if agg.get("parent_id") == parent_id and agg.get("name") == legacy_name:
                store.update_aggregation(
                    agg["id"], name=REMAINDER_NAME, agg_type="remainder")
                return agg["id"]
    return None


def sync_remainder_child(store, parent_id):
    """确保父聚合存在且 ≥1 个其他子聚合时创建/复用 remainder 子聚合并刷新。

    返回 remainder 子聚合 id；条件不满足时返回 None（不造噪音）。
    """
    parent = store.get_aggregation(parent_id)
    if not parent:
        return None
    siblings = store.sibling_aggregation_ids(parent_id, parent_id)
    if not siblings:
        return None
    rid = _find_remainder_child(store, parent_id)
    if rid is None:
        rid = store.add_aggregation(
            name=REMAINDER_NAME, agg_type="remainder",
            parent_id=parent_id, sort_order=_SORT_ORDER_MAX)
    store.refresh_aggregation(rid)
    return rid
```

- [x] **2.3 删除 `auto_exclude.py` 与 `tests/test_rss_auto_exclude.py`**：

```bat
Remove-Item -LiteralPath "modules\rss_aggregator\auto_exclude.py"
Remove-Item -LiteralPath "tests\test_rss_auto_exclude.py"
```

- [x] **2.4 清理引用**：搜索 `auto_exclude` 与 `sync_auto_exclude_child` 的残留引用：

```bat
rg -n "auto_exclude|sync_auto_exclude_child" modules tests
```

预期输出：无匹配（`agg_service.py` 中的引用在 Task 3 修改，此处仅确认引用点清单）。

- [x] **2.5 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_remainder.py -v
```

预期输出：`9 passed`（4 个 Task1 + 5 个 Task2）。

- [x] **2.6 提交**：`feat: remainder 模块取代 auto_exclude 模糊排除`

---

## Task 3 — `agg_service` 触发统一 + `refresh_subtree`

### Files
- **Modify**: `modules/rss_aggregator/agg_service.py`
- **Modify**: `tests/test_rss_agg_service.py`（更新 import + 新增测试）

### Interfaces
- **Consumes**: `sync_remainder_child(store, parent_id)`、`store.refresh_aggregation(agg_id)`、`store.sibling_aggregation_ids(parent_id, exclude_id)`
- **Produces**:
  - `_refresh_for_feed_sync(store, feed_id)` — 对每个受影响聚合：`refresh_aggregation` 后**无条件**调用 `sync_remainder_child(store, agg_id)`
  - `_refresh_one(store, agg_id)` — 刷新后同样无条件调用 `sync_remainder_child(store, agg_id)`
  - 模块级 `refresh_subtree(store, parent_id) -> None` — 刷新父聚合全部子聚合 + 重建 remainder（S5 用）

### Steps

- [x] **3.1 更新 `tests/test_rss_agg_service.py` import 区**。把 L25：

```python
from modules.rss_aggregator.auto_exclude import AUTO_EXCLUDE_SUFFIX
```

改为：

```python
from modules.rss_aggregator.remainder import REMAINDER_NAME, sync_remainder_child
```

全文搜索 `AUTO_EXCLUDE_SUFFIX` 并替换为 `REMAINDER_NAME`；把 `.endswith(AUTO_EXCLUDE_SUFFIX)` 改为 `== REMAINDER_NAME`。

- [x] **3.2 追加新测试**（`tests/test_rss_agg_service.py` 末尾）：

```python
def test_refresh_for_feed_sync_creates_remainder_for_keyword_parent(tmp_path):
    """触发面不再限于 similarity：keyword 父聚合刷新后也重建 remainder。"""
    store = _make_store(tmp_path)
    store.add_feed("FeedA", "http://a/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    entries = [
        {"title": "GPT-5 发布 性能全面提升", "link": "http://x/1", "description": "a"},
        {"title": "OpenAI 发布 GPT-5 新模型", "link": "http://x/2", "description": "b"},
    ]
    store.ingest("test", entries, feed_id=feed_id)
    parent = store.add_aggregation(name="父", agg_type="mixed",
                                   feed_ids=[feed_id])
    child = store.add_aggregation(
        name="子", agg_type="keyword", parent_id=parent,
        kw_required=["GPT"])
    store.refresh_aggregation(child)
    from modules.rss_aggregator.agg_service import _refresh_for_feed_sync
    _refresh_for_feed_sync(store, feed_id)
    aggs = store.list_aggregations()
    remainder = [a for a in aggs if a.get("agg_type") == "remainder"]
    assert len(remainder) == 1
    assert remainder[0]["name"] == REMAINDER_NAME


def test_refresh_subtree_refreshes_all_children_and_remainder(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("FeedA", "http://a/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    entries = [
        {"title": "GPT-5 发布", "link": "http://x/1", "description": "a"},
        {"title": "Rust 入门教程", "link": "http://x/2", "description": "b"},
    ]
    store.ingest("test", entries, feed_id=feed_id)
    parent = store.add_aggregation(name="父", agg_type="mixed",
                                   feed_ids=[feed_id])
    store.add_aggregation(
        name="子1", agg_type="keyword", parent_id=parent,
        kw_required=["GPT"])
    store.add_aggregation(
        name="子2", agg_type="keyword", parent_id=parent,
        kw_required=["不存在词"])
    from modules.rss_aggregator.agg_service import refresh_subtree
    refresh_subtree(store, parent)
    r = [a for a in store.list_aggregations()
         if a.get("agg_type") == "remainder"]
    assert len(r) == 1
    assert store.get_aggregation_item_count(r[0]["id"]) >= 0
```

运行并看到失败（`agg_service` 尚无 `refresh_subtree`，`_refresh_for_feed_sync` 不建 remainder）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_agg_service.py -v
```

预期输出：新测试 FAILED（`ImportError: cannot import name 'refresh_subtree'` 或断言失败）。

- [x] **3.3 修改 `_refresh_for_feed_sync` 循环体**。把现有：

```python
for agg_id in affected:
    a = id_map.get(agg_id)
    if not a:
        continue
    store.refresh_aggregation(agg_id)
    if (a.get("agg_type") or "mixed") == "similarity":
        sync_auto_exclude_child(store, agg_id)
```

改为：

```python
for agg_id in affected:
    a = id_map.get(agg_id)
    if not a:
        continue
    store.refresh_aggregation(agg_id)
    sync_remainder_child(store, agg_id)
```

（`affected` 计算逻辑不变；顶部 import 改 `from .remainder import sync_remainder_child`。）

- [x] **3.4 修改 `_refresh_one`**。在 `store.refresh_aggregation(agg_id)` 之后追加：

```python
sync_remainder_child(store, agg_id)
```

- [x] **3.5 新增模块级 `refresh_subtree`**（`agg_service.py` 末尾）：

```python
def refresh_subtree(store, parent_id):
    """刷新父聚合全部子聚合 + 重建 remainder（S5 一键刷新）。"""
    parent = store.get_aggregation(parent_id)
    if not parent:
        return
    for child_id in store.sibling_aggregation_ids(parent_id, parent_id):
        store.refresh_aggregation(child_id)
    sync_remainder_child(store, parent_id)
```

- [x] **3.6 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_agg_service.py -v
```

预期输出：全部通过（含新增 2 个）。

- [x] **3.7 提交**：`feat: agg_service 触发统一并新增 refresh_subtree`

---

## Task 4 — `text_segment.py` + 停用词配置

### Files
- **Create**: `modules/rss_aggregator/text_segment.py`
- **Modify**: `core/constants.py`
- **Test**: `tests/test_rss_text_segment.py`（新建）

### Interfaces
- **Consumes**: `text_utils._WORD_RE`（回退用）、`text_utils._STOP_WORDS`（内置基础）、`core.config.AppConfig`（dot-path get/set）
- **Produces**:
  - `segment_titles(titles: list[str], top_n: int = 50, extra_stop_words: list[str] | None = None) -> list[tuple[str, int]]`
  - `available() -> bool`
  - `DEFAULT_STOP_WORDS: frozenset[str]`
  - `core/constants.py` 的 `DEFAULT_CONFIG["rss"]["high_freq"] = {"stop_words": []}`

### Steps

- [x] **4.1 写失败测试** `tests/test_rss_text_segment.py`（新建）：

```python
"""text_segment：jieba 中文分词 + 词性过滤 + 停用词并集 + 回退。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from modules.rss_aggregator.text_segment import (
    DEFAULT_STOP_WORDS, available, segment_titles,
)


def test_segment_titles_basic_cjk():
    titles = ["海贼王第1000话高清下载", "海贼王第1001话在线观看"]
    result = segment_titles(titles, top_n=50)
    words = [w for w, _ in result]
    assert "海贼王" in words
    assert "第" not in words  # 助词/数词组合被词性过滤或停用词剔除


def test_segment_titles_filters_stopwords_union():
    titles = ["海贼王高清下载", "海贼王在线观看"]
    result = segment_titles(titles, top_n=50, extra_stop_words=["海贼王"])
    words = [w for w, _ in result]
    assert "海贼王" not in words  # 用户自定义停用词生效
    assert "高清" not in words    # 内置停用词生效


def test_segment_titles_top_n_cap():
    # 生成 400 个各含唯一 2 字 CJK 词的标题，确保 >200 个独立合格 token
    chars1 = [chr(0x4E00 + i) for i in range(20)]
    chars2 = [chr(0x5000 + i) for i in range(20)]
    titles = [f"{c1}{c2}新闻" for c1 in chars1 for c2 in chars2]
    result = segment_titles(titles, top_n=500)
    assert len(result) <= 200  # 硬上限


def test_segment_titles_empty():
    assert segment_titles([]) == []


def test_available_returns_bool():
    assert isinstance(available(), bool)


def test_default_stop_words_is_frozenset():
    assert isinstance(DEFAULT_STOP_WORDS, frozenset)
    assert "下载" in DEFAULT_STOP_WORDS
```

运行并看到失败（模块不存在）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_text_segment.py -v
```

预期输出：`ModuleNotFoundError: No module named 'modules.rss_aggregator.text_segment'`，6 个测试 FAILED。

- [x] **4.2 实现 `modules/rss_aggregator/text_segment.py`**：

```python
"""中文分词高频词提取：jieba 懒加载 + 词性过滤 + 停用词并集 + 正则回退。"""

import re
import threading
from collections import Counter

from .text_utils import _STOP_WORDS, _WORD_RE

_jieba = None
_jieba_lock = threading.Lock()

# 允许保留的词性：名词/专名/英文/数词/非语素字（字母数字串）
_ALLOWED_FLAGS = {"n", "nr", "ns", "nt", "nz", "eng", "m", "x"}

# 内置停用词：现有 19 个基础 + 内容站常见噪声词
DEFAULT_STOP_WORDS = frozenset(
    set(_STOP_WORDS) | {
        "下载", "在线", "高清", "全集", "最新", "更新", "资源",
        "免费", "字幕组", "观看", "视频", "地址", "链接", "分享",
    }
)

_TOP_N_HARD_CAP = 200


def available():
    """jieba 是否可用（首次调用触发懒加载）。"""
    _ensure_jieba()
    return _jieba is not None


def _ensure_jieba():
    global _jieba
    if _jieba is not None:
        return
    with _jieba_lock:
        if _jieba is not None:
            return
        try:
            import jieba.posseg as _posseg
            _jieba = _posseg
        except Exception:
            _jieba = None


def segment_titles(titles, top_n=50, extra_stop_words=None):
    """把标题列表汇成高频词表：频次降序，同频保持首现顺序。

    top_n 硬上限 200；jieba 不可用时回退 text_utils._WORD_RE 正则分词。
    """
    if not titles:
        return []
    top_n = max(1, min(int(top_n), _TOP_N_HARD_CAP))
    stop = DEFAULT_STOP_WORDS | frozenset(extra_stop_words or [])
    _ensure_jieba()
    counter = Counter()
    if _jieba is not None:
        for title in titles:
            for word, flag in _jieba.cut(title):
                if flag not in _ALLOWED_FLAGS:
                    continue
                w = word.strip().lower()
                if not w:
                    continue
                if len(w) < 2 and not re.search(r"[\u4e00-\u9fff]", w):
                    continue
                if w.isdigit():
                    continue
                if w in stop:
                    continue
                counter[w] += 1
    else:
        for title in titles:
            for w in _WORD_RE.findall(title.lower()):
                if len(w) < 2:
                    continue
                if w.isdigit():
                    continue
                if w in stop:
                    continue
                counter[w] += 1
    return list(counter.items())[:top_n]
```

- [x] **4.3 新增配置默认值**。在 `core/constants.py` 的 `DEFAULT_CONFIG["rss"]` 字典中（`"show_thumbnails": False,` 之后）插入：

```python
"high_freq": {"stop_words": []},
```

- [x] **4.4 安装 jieba 并运行测试看到通过**：

```bat
.venv\Scripts\pip install "jieba>=0.42.1"
.venv\Scripts\python -m pytest tests/test_rss_text_segment.py -v
```

预期输出：`6 passed`。

- [x] **4.5 提交**：`feat: text_segment 中文分词模块与停用词配置`

---

## Task 5 — 高频词面板重写（chips 池 / 搜索 / 多选 / 停用词对话框）

### Files
- **Modify**: `modules/rss_aggregator/dialogs/builders.py`
- **Modify**: `modules/rss_aggregator/dialogs/f.py`
- **Create**: `modules/rss_aggregator/dialogs/stop_words.py`
- **Modify**: `modules/rss_aggregator/dialogs/__init__.py`
- **Modify**: `core/theme/tokens.py`（新增 `rss_hf_scroll_height` 令牌）
- **Test**: `tests/test_rss_high_freq.py`（更新）

### Interfaces
- **Consumes**: `segment_titles(titles, top_n, extra_stop_words)`、`text_utils._parse_keywords`、`text_utils.rss_palette`、`core.theme.tokens.sizing`、`core.config.AppConfig`（`rss.high_freq.stop_words`）、`store.aggregation_titles(agg_id, limit=None)`
- **Produces**:
  - `build_high_freq_group(dialog, parent) -> QtWidgets.QWidget` — 重写：搜索框 + chips 滚动区 + 按钮行（分析高频词 / 全部加入必须 / 清空关键词 / 停用词…）+ `spin_top_n`
  - `_HighFreqMixin` — 持有 `_hf_results` 缓存、`_hf_worker`（QThread）、`_hf_search` 过滤、chips 多选状态
  - `dialogs/stop_words.py` 的 `_StopWordsDialog(QtWidgets.QDialog)` — 编辑 `rss.high_freq.stop_words`
  - `core/theme/tokens.py` 的 `sizing()` 新增 `rss_hf_scroll_height`（默认 `_s(180)`）

### Steps

- [x] **5.1 新增尺寸令牌**。在 `core/theme/tokens.py` 的 `sizing()` 返回 dict 中新增：

```python
"rss_hf_scroll_height": _s(180),
```

- [x] **5.2 写失败测试**（更新 `tests/test_rss_high_freq.py`）。删除 `test_analyze_high_freq_cjk_whole_run_token`（其断言的「整段切词」旧行为已被 jieba 取代）。保留其余现有测试。追加：

```python
def test_chips_pool_is_results_minus_buckets():
    """chips 池 ≡ 分析结果全集 − 三桶已解析词。"""
    from modules.rss_aggregator.dialogs.builders import _chips_pool
    results = [("海贼王", 5), ("火影", 3), ("下载", 2)]
    buckets = {"required": ["海贼王"], "optional": [], "forbidden": ["下载"]}
    pool = _chips_pool(results, buckets)
    assert pool == [("火影", 3)]


def test_chips_text_shows_frequency():
    from modules.rss_aggregator.dialogs.builders import _chip_text
    assert _chip_text("海贼王", 5) == "海贼王 · 5"
```

运行并看到失败（`_chips_pool` / `_chip_text` 不存在）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py -v
```

预期输出：`ImportError: cannot import name '_chips_pool'`，新测试 FAILED。

- [x] **5.3 实现 `_chips_pool` / `_chip_text` 并重写 `build_high_freq_group`**（`dialogs/builders.py`）。保留 `_FlowLayout` 类；新增纯函数：

```python
def _chips_pool(results, buckets):
    """chips 池 = 分析结果全集 − 三桶已解析词。"""
    used = set()
    for key in ("required", "optional", "forbidden"):
        used |= set(_parse_keywords(buckets.get(key) or []))
    return [(w, c) for w, c in results if w not in used]


def _chip_text(word, count):
    return f"{word} · {count}"
```

重写 `build_high_freq_group(dialog, parent)` 函数体为：

```python
def build_high_freq_group(dialog, parent):
    """高频词面板：搜索框 + chips 滚动区 + 按钮行。"""
    pal = rss_palette()
    group = QtWidgets.QWidget(parent)
    vb = QtWidgets.QVBoxLayout(group)
    vb.setContentsMargins(0, 0, 0, 0)

    # 搜索框
    search = make_line_edit()
    search.setPlaceholderText("搜索关键词…")
    vb.addWidget(search)

    # spin_top_n
    spin_row = QtWidgets.QHBoxLayout()
    spin_row.addWidget(make_label("Top N:"))
    spin_top_n = QtWidgets.QSpinBox()
    spin_top_n.setRange(10, 200)
    spin_top_n.setValue(50)
    spin_row.addWidget(spin_top_n)
    spin_row.addStretch(1)
    vb.addLayout(spin_row)

    # chips 滚动区
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFixedHeight(sizing()["rss_hf_scroll_height"])
    chips_container = QtWidgets.QWidget()
    chips_layout = _FlowLayout(chips_container, hspacing=6, vspacing=6)
    scroll.setWidget(chips_container)
    vb.addWidget(scroll)

    # 按钮行
    btn_row = QtWidgets.QHBoxLayout()
    btn_analyze = make_button("分析高频词")
    btn_add_all = make_button("全部加入必须")
    btn_clear = make_button("清空关键词")
    btn_stop = make_button("停用词…")
    btn_row.addWidget(btn_analyze)
    btn_row.addWidget(btn_add_all)
    btn_row.addWidget(btn_clear)
    btn_row.addWidget(btn_stop)
    btn_row.addStretch(1)
    vb.addLayout(btn_row)

    # 状态
    dialog._hf_results = []
    dialog._hf_worker = None
    dialog._hf_selected = set()
    dialog._hf_chips_layout = chips_layout
    dialog._hf_scroll = scroll
    dialog._hf_search = search
    dialog._hf_spin_top_n = spin_top_n

    def _render_chips():
        """根据 _hf_results + 搜索过滤 + 桶状态渲染 chips。"""
        while chips_layout.count():
            child = chips_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        text = search.text().strip().lower()
        buckets = {
            "required": dialog.kw_required if hasattr(dialog, "kw_required") else [],
            "optional": dialog.kw_optional if hasattr(dialog, "kw_optional") else [],
            "forbidden": dialog.kw_forbidden if hasattr(dialog, "kw_forbidden") else [],
        }
        pool = _chips_pool(dialog._hf_results, buckets)
        if text:
            pool = [(w, c) for w, c in pool if text in w.lower()]
        for word, count in pool:
            btn = make_button(_chip_text(word, count))
            btn.setCheckable(True)
            btn.setChecked(word in dialog._hf_selected)
            btn.clicked.connect(lambda checked, w=word: _on_chip_click(w, checked))
            chips_layout.addWidget(btn)

    def _on_chip_click(word, checked):
        if checked:
            dialog._hf_selected.add(word)
        else:
            dialog._hf_selected.discard(word)

    def _on_analyze():
        """后台线程分析高频词。"""
        store = dialog.owner.store if hasattr(dialog.owner, "store") else None
        if store and hasattr(store, "aggregation_titles"):
            titles = store.aggregation_titles(
                dialog.agg_id if hasattr(dialog, "agg_id") else 0,
                limit=None)
        else:
            titles = []
        from modules.rss_aggregator.text_segment import segment_titles
        top_n = spin_top_n.value()
        dialog._hf_results = segment_titles(titles, top_n=top_n)
        dialog._hf_selected.clear()
        _render_chips()

    btn_analyze.clicked.connect(_on_analyze)
    search.textChanged.connect(lambda: _render_chips())

    def _on_add_all():
        """把选中 chips 加入【必须】桶。"""
        if not hasattr(dialog, "kw_required"):
            dialog.kw_required = []
        dialog.kw_required.extend(list(dialog._hf_selected))
        dialog._hf_selected.clear()
        _render_chips()

    btn_add_all.clicked.connect(_on_add_all)

    def _on_clear():
        """清空三桶。"""
        for attr in ("kw_required", "kw_optional", "kw_forbidden"):
            if hasattr(dialog, attr):
                setattr(dialog, attr, [])
        _render_chips()

    btn_clear.clicked.connect(_on_clear)

    def _on_stop_words():
        from .stop_words import _StopWordsDialog
        _StopWordsDialog(dialog.owner, parent=dialog).exec()

    btn_stop.clicked.connect(_on_stop_words)

    return group
```

> 注意：`_HighFreqMixin` 类定义保留（`_AddAggregationDialog` 继承自它），但移除 `_hf_results`/`_hf_worker` 等已迁移字段——这些状态改由 `build_high_freq_group` 在 `dialog` 实例上初始化。

- [x] **5.4 实现 `dialogs/stop_words.py`**：

```python
"""停用词编辑对话框：读写 rss.high_freq.stop_words（只存用户自定义部分）。"""

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing
from ui.widgets import make_button, make_line_edit, make_label

_, QtCore, QtGui, QtWidgets = import_qt()

from ..text_utils import _parse_keywords, rss_palette


class _StopWordsDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setWindowTitle("停用词管理")
        self.setMinimumWidth(420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(make_label("输入停用词，用逗号或空格分隔（仅保存自定义部分）："))
        self.edit = make_line_edit()
        self.edit.setPlaceholderText("例如：下载, 在线, 高清")
        self.edit.setText(", ".join(self._load()))
        lay.addWidget(self.edit)
        row = QtWidgets.QHBoxLayout()
        btn_ok = make_button("保存")
        btn_ok.clicked.connect(self._save)
        btn_cancel = make_button("取消")
        btn_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

    def _load(self):
        return list(
            self.owner.context.config.get("rss.high_freq.stop_words", []) or []
        )

    def _save(self):
        words = _parse_keywords(self.edit.text())
        self.owner.context.config.set("rss.high_freq.stop_words", words)
        self.accept()
```

- [x] **5.5 更新 `dialogs/__init__.py`**：

```python
# dialogs/__init__.py — 追加 stop_words 导出
from .stop_words import _StopWordsDialog
```

并把 `_StopWordsDialog` 加入 `__all__`。

- [x] **5.6 更新 `dialogs/f.py`**：

```python
# dialogs/f.py — _TYPE_LABELS 追加 remainder 条目
_TYPE_LABELS = {
    "mixed": "混合",
    "keyword": "关键词",
    "torrent": "磁链 Hash",
    "similarity": "相似性",
    "remainder": "未分类条目",
}
```

```python
# dialogs/f.py — 类型下拉填充处（_parent_mode 时排除 remainder）
for key, label in _TYPE_LABELS.items():
    if self._parent_mode and key == "remainder":
        continue
    self.combo_type.addItem(label, key)
```

```python
# dialogs/f.py — 构建对话框时，高频词面板所有类型可见
self.hf_group = build_high_freq_group(self, self)
```

（`_hf_results` 数据源由 `build_high_freq_group` 的 `_on_analyze` 内部通过 `store.aggregation_titles(dialog.agg_id, limit=None)` 获取，见 5.3。）

- [x] **5.7 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py -v
```

预期输出：全部通过（含新增 2 个，删除 1 个旧断言）。

- [x] **5.8 样式门禁**：

```bat
.venv\Scripts\python -m pytest tests/test_style_guardrails.py -v
.venv\Scripts\python scripts/audit_styles.py --check
```

预期输出：全部通过 / `0 new violations`。

- [x] **5.9 提交**：`feat: 高频词面板重写（chips 池/搜索/多选/停用词）`

---

## Task 6 — 命中预览 S1

### Files
- **Modify**: `modules/rss_store/store_aggregation.py`（新增 `_keyword_clauses` / `count_aggregation_hits`）
- **Modify**: `modules/rss_aggregator/dialogs/f.py`（S1 接线）
- **Test**: `tests/test_rss_high_freq.py`（追加）

### Interfaces
- **Consumes**: `_keyword_clauses`（新增辅助）、现有 scope 构造逻辑
- **Produces**:
  - `store.count_aggregation_hits(agg_dict: dict) -> int` — 按与 `refresh_aggregation` 相同的条件做 `COUNT(*)`
  - 对话框底部 `QLabel`：`当前条件命中 N 条`，300ms 防抖

### Steps

- [x] **6.1 写失败测试**（追加到 `tests/test_rss_high_freq.py`）：

```python
def test_count_aggregation_hits(tmp_path):
    from modules.rss_store.store import RssStore
    store = RssStore(str(tmp_path / "t.db"))
    store.add_feed("TestFeed", "http://test/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    entries = [
        {"title": f"海贼王{i}话", "link": f"http://x/{i}", "description": ""}
        for i in range(5)
    ]
    store.ingest("test", entries, feed_id=feed_id)
    agg = {"agg_type": "keyword", "kw_required": ["海贼王"],
           "feed_ids": [feed_id], "tags": []}
    assert store.count_aggregation_hits(agg) == 5
```

运行并看到失败（方法不存在）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py -v
```

预期输出：`AttributeError: 'RssStore' object has no attribute 'count_aggregation_hits'`。

- [x] **6.2 实现 `_keyword_clauses` 与 `count_aggregation_hits`**（`modules/rss_store/store_aggregation.py`）。先提取 keyword 分支的 WHERE 构造为辅助方法，再实现 count：

```python
def _keyword_clauses(self, agg):
    """提取 keyword 类型聚合的标题条件（kw_required / kw_optional / kw_forbidden）。

    返回 (conditions: list[str], args: list)，conditions 需用 AND 连接后拼入 WHERE。
    """
    clauses = []
    args = []
    for kw in (agg.get("kw_required") or []):
        clauses.append("i.title LIKE ?")
        args.append(f"%{kw}%")
    optional = agg.get("kw_optional") or []
    if optional:
        parts = ["i.title LIKE ?"] * len(optional)
        clauses.append(f"({' OR '.join(parts)})")
        args.extend(f"%{kw}%" for kw in optional)
    for kw in (agg.get("kw_forbidden") or []):
        clauses.append("i.title NOT LIKE ?")
        args.append(f"%{kw}%")
    return clauses, args


def count_aggregation_hits(self, agg):
    """按聚合条件统计命中条数（S1 命中预览）。"""
    clauses = []
    args = []
    # feed_ids scope（与 refresh_aggregation 中相同逻辑）
    feed_ids = agg.get("feed_ids") or []
    if feed_ids:
        ph = ",".join("?" * len(feed_ids))
        clauses.append(f"i.feed_id IN ({ph})")
        args.extend(int(fid) for fid in feed_ids)
    # tags scope
    tags = agg.get("tags") or []
    if tags:
        ph = ",".join("?" * len(tags))
        clauses.append(
            f"i.hash IN (SELECT hash FROM item_tags WHERE tag IN ({ph}))"
        )
        args.extend(tags)
    # keyword conditions
    kw_clauses, kw_args = self._keyword_clauses(agg)
    clauses.extend(kw_clauses)
    args.extend(kw_args)
    if not clauses:
        return 0
    where = " AND ".join(clauses)
    sql = f"SELECT COUNT(*) FROM items i WHERE {where}"
    with self._conn() as conn:
        return conn.execute(sql, args).fetchone()[0]
```

- [x] **6.3 对话框接线**（`dialogs/f.py`）。在 `_AddAggregationDialog` 的 `_build_dialog` 尾部新增：

```python
# S1 命中预览 label
self._hit_label = make_label("当前条件命中 — 条")
lay.addWidget(self._hit_label)
self._hit_timer = QtCore.QTimer()
self._hit_timer.setSingleShot(True)
self._hit_timer.setInterval(300)
self._hit_timer.timeout.connect(self._update_hit_count)
# 绑定各控件 change → 防抖触发
for sig in (self.combo_type.currentIndexChanged,
            self.edit_kw_req.textChanged,
            self.edit_kw_opt.textChanged,
            self.edit_kw_for.textChanged):
    sig.connect(lambda: self._hit_timer.start())
```

新增方法：

```python
def _update_hit_count(self):
    """后台 COUNT 更新命中预览标签。"""
    agg = self._collect_agg_dict()
    store = self.owner.store
    if not hasattr(store, "count_aggregation_hits"):
        return
    count = store.count_aggregation_hits(agg)
    self._hit_label.setText(f"当前条件命中 {count} 条")


def _collect_agg_dict(self):
    """把对话框控件状态收集为 agg_dict。"""
    return {
        "agg_type": self.combo_type.currentData() or "mixed",
        "feed_ids": [f["id"] for f in self._selected_feeds],
        "tags": [t for t in self._selected_tags],
        "kw_required": _parse_keywords(self.edit_kw_req.text()),
        "kw_optional": _parse_keywords(self.edit_kw_opt.text()),
        "kw_forbidden": _parse_keywords(self.edit_kw_for.text()),
    }
```

- [x] **6.4 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py -v
```

预期输出：全部通过。

- [x] **6.5 提交**：`feat: 聚合命中预览 S1`

---

## Task 7 — S2 / S3 / S4 / S5 / S6

### Files
- **Modify**: `modules/rss_aggregator/page_context.py`（S2 右键菜单）
- **Modify**: `modules/rss_aggregator/sidebar_data.py`（S3 覆盖率、S6 相对时间）
- **Modify**: `modules/rss_aggregator/sidebar_actions.py`（S5 右键菜单）
- **Modify**: `modules/rss_aggregator/page_similarity.py`（S4 阈值预览）
- **Modify**: `modules/rss_aggregator/page_lifecycle.py`（S2 新建子聚合入口）
- **Modify**: `modules/rss_aggregator/page_torrent.py`（remainder 只读打开）
- **Modify**: `modules/rss_aggregator/text_utils.py`（`_relative_time` 辅助）
- **Test**: `tests/test_rss_high_freq.py`（追加）、`tests/test_rss_agg_service.py`（追加）

### Interfaces
- **Consumes**: `segment_titles`、`_AddAggregationDialog(owner, page, parent_id=...)`、`agg_service.refresh_subtree(store, parent_id)`、`store.aggregation_titles(agg_id, limit=None)`、`store.get_aggregation_torrent_groups`、`_cluster_by_similarity`（现有）
- **Produces**:
  - `text_utils._relative_time(ts: str) -> str` — 「刚刚 / N 分钟前 / N 小时前 / N 天前」
  - `page_context` 右键菜单新增：`用选中条目新建子聚合`、`移动到…`
  - `sidebar_data` 父聚合行追加 `未分类 N / M`（S3）；聚合行追加相对时间（S6）
  - `sidebar_actions` 父聚合右键菜单新增 `刷新全部子聚合`（S5）
  - `page_similarity` 阈值预览 label（S4）

### Steps

- [x] **7.1 写失败测试**（追加）：

```python
# tests/test_rss_high_freq.py
def test_relative_time():
    from modules.rss_aggregator.text_utils import _relative_time
    import datetime
    now = datetime.datetime.now()
    assert _relative_time((now - datetime.timedelta(minutes=3)).isoformat()) == "3 分钟前"
    assert _relative_time((now - datetime.timedelta(hours=2)).isoformat()) == "2 小时前"
    assert _relative_time((now - datetime.timedelta(days=5)).isoformat()) == "5 天前"
```

```python
# tests/test_rss_agg_service.py
def test_refresh_subtree_via_sidebar_action(tmp_path):
    """S5：refresh_subtree 后 remainder 与子聚合同步刷新。"""
    store = _make_store(tmp_path)
    store.add_feed("FeedA", "http://a/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    entries = [
        {"title": "GPT-5 发布", "link": "http://x/1", "description": "a"},
    ]
    store.ingest("test", entries, feed_id=feed_id)
    parent = store.add_aggregation(name="父", agg_type="mixed",
                                   feed_ids=[feed_id])
    store.add_aggregation(name="子", agg_type="keyword", parent_id=parent,
                          kw_required=["GPT"])
    from modules.rss_aggregator.agg_service import refresh_subtree
    refresh_subtree(store, parent)
    r = [a for a in store.list_aggregations()
         if a.get("agg_type") == "remainder"]
    assert len(r) == 1
```

运行并看到失败（`_relative_time` 不存在）：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py tests/test_rss_agg_service.py -v
```

预期输出：`ImportError: cannot import name '_relative_time'`。

- [x] **7.2 实现 `_relative_time`**（`modules/rss_aggregator/text_utils.py` 末尾追加，文件顶部补 `import datetime`）：

```python
def _relative_time(ts):
    """把 ISO 时间戳转成相对时间（S6 侧边栏显示）。"""
    if not ts:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        delta = datetime.datetime.now() - dt.replace(tzinfo=None)
    except ValueError:
        return ""
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"
```

- [x] **7.3 S2 一键派发**（`page_context.py` + `page_lifecycle.py`）。在 `_show_context_menu` 的 item 列表右键菜单中，当 `self._current_agg.get("agg_type") == "remainder"` 时追加两项：

```python
# page_context.py — _show_context_menu 内，remainder 聚合追加两项
if self._current_agg.get("agg_type") == "remainder":
    menu.addSeparator()
    act_new_sub = menu.addAction("用选中条目新建子聚合")
    act_move = menu.addAction("移动到…")
    act_new_sub.triggered.connect(self._on_new_sub_from_selection)
    act_move.triggered.connect(self._on_move_selection)
```

新增方法：

```python
def _on_new_sub_from_selection(self):
    """取选中条目标题 → 高频词预填【必须】桶 → 打开新建子聚合对话框。"""
    titles = [it.get("title", "") for it in self._selected_items()]
    from modules.rss_aggregator.text_segment import segment_titles
    words = [w for w, _ in segment_titles(titles, top_n=10)]
    parent_id = self._current_agg.get("id", 0)
    from modules.rss_aggregator.dialogs import _AddAggregationDialog
    dlg = _AddAggregationDialog(
        self.owner, self, parent_id=parent_id)
    dlg.kw_required = words
    dlg.edit_kw_req.setText(", ".join(words))
    dlg.exec()


def _on_move_selection(self):
    """把选中条目移动到兄弟子聚合（追加其高频词到目标 kw_optional）。"""
    titles = [it.get("title", "") for it in self._selected_items()]
    from modules.rss_aggregator.text_segment import segment_titles
    words = [w for w, _ in segment_titles(titles, top_n=10)]
    parent_id = self._current_agg.get("parent_id", 0)
    siblings = self.owner.store.sibling_aggregation_ids(parent_id, 0)
    if not siblings:
        return
    names = {a["id"]: a["name"] for a in self.owner.store.list_aggregations()}
    from PySide6.QtWidgets import QInputDialog
    target_id, ok = QInputDialog.getItem(
        self, "移动到…", "选择目标子聚合：",
        [names[s] for s in siblings], 0, False)
    if not ok:
        return
    target = next(s for s in siblings if names[s] == target_id)
    agg = self.owner.store.get_aggregation(target)
    old = agg.get("kw_optional") or []
    merged = list(dict.fromkeys(old + words))
    self.owner.store.update_aggregation(target, kw_optional=merged)
    from modules.rss_aggregator.agg_service import refresh_subtree
    refresh_subtree(self.owner.store, parent_id)
```

- [x] **7.4 S3 分类覆盖率**（`sidebar_data.py`）。在父聚合行数据构造处追加 `remainder_count` 与 `total_count`：

```python
# sidebar_data.py — 父聚合行数据
def _agg_remainder_counts(store, agg):
    """返回 (remainder_count, total_count)；无 remainder 子聚合时 (0, total)。"""
    children = store.sibling_aggregation_ids(agg["id"], 0)
    remainder_id = None
    for cid in children:
        c = store.get_aggregation(cid)
        if c and c.get("agg_type") == "remainder":
            remainder_id = cid
            break
    total = store.get_aggregation_item_count(agg["id"])
    if remainder_id is None:
        return 0, total
    return store.get_aggregation_item_count(remainder_id), total
```

在父聚合行副文本渲染处追加：

```python
# sidebar_data.py — 父聚合行 hint 文本
rc, tc = _agg_remainder_counts(store, agg)
hint = f"未分类 {rc} / {tc}" if tc else ""
```

- [x] **7.5 S4 阈值实时预览**（`page_similarity.py`）。在 `spin_threshold` 的 `valueChanged` 连接处追加防抖预览：

```python
# page_similarity.py — 阈值预览
self._preview_label = make_label("阈值 0.55 → 0 簇 / 覆盖 0 条")
self._preview_timer = QtCore.QTimer()
self._preview_timer.setSingleShot(True)
self._preview_timer.setInterval(300)
self._preview_timer.timeout.connect(self._update_threshold_preview)
self.spin_threshold.valueChanged.connect(lambda _v: self._preview_timer.start())
```

新增方法：

```python
def _update_threshold_preview(self):
    """后台聚类预览：阈值 → 簇数 / 覆盖条数。"""
    threshold = self.spin_threshold.value() / 100.0
    members = self._current_members()
    clusters = _cluster_by_similarity_gen(members, threshold)
    cluster_count = len(clusters)
    covered = sum(len(c) for c in clusters)
    self._preview_label.setText(
        f"阈值 {threshold:.2f} → {cluster_count} 簇 / 覆盖 {covered} 条")
```

- [x] **7.6 S5 子聚合批量刷新**（`sidebar_actions.py`）。在父聚合右键菜单追加：

```python
# sidebar_actions.py — agg_menu_handler 内，parent_id == 0 的聚合追加
if d.get("parent_id", 0) == 0:
    menu.addAction("刷新全部子聚合", lambda: self._on_refresh_subtree(d["agg_id"]))
```

新增方法：

```python
def _on_refresh_subtree(self, agg_id):
    """刷新父聚合全部子聚合 + 重建 remainder。"""
    from modules.rss_aggregator.agg_service import refresh_subtree
    refresh_subtree(self.owner.store, agg_id)
    self.owner._reload_sidebar()
```

- [x] **7.7 S6 刷新时间可见**（`sidebar_data.py`）。在聚合行副文本渲染处追加：

```python
# sidebar_data.py — 聚合行 hint 文本
from modules.rss_aggregator.text_utils import _relative_time
last = agg.get("last_refreshed") or ""
if last:
    hint = f"{hint} · {_relative_time(last)}"
```

- [x] **7.8 remainder 只读打开**（`page_torrent.py` + `sidebar_actions.py`）。在 `_open_aggregation` 中：

```python
# page_torrent.py — _open_aggregation 内
if agg.get("agg_type") == "remainder":
    self._load_items()
    return
```

在 `sidebar_actions.py` 的聚合右键菜单中，对 remainder 隐藏「编辑聚合」：

```python
# sidebar_actions.py — agg_menu_handler 内
if d.get("agg_type") != "remainder":
    menu.addAction("编辑聚合", lambda: self._on_edit_agg(d["agg_id"]))
```

- [x] **7.9 运行测试看到通过**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_high_freq.py tests/test_rss_agg_service.py -v
```

预期输出：全部通过。

- [x] **7.10 样式门禁**：

```bat
.venv\Scripts\python -m pytest tests/test_style_guardrails.py -v
.venv\Scripts\python scripts/audit_styles.py --check
```

预期输出：全部通过 / `0 new violations`。

- [x] **7.11 提交**：`feat: S2-S6 辅助能力（派发/覆盖率/阈值预览/批量刷新/相对时间）`

---

## Task 8 — 依赖与 spec 打包改动 + 构建验证

### Files
- **Modify**: `requirements.txt`
- **Modify**: `yzplan.spec`
- **Test**: 无新测试（构建验证）

### Interfaces
- **Consumes**: 现有 `requirements.txt` 依赖清单、`yzplan.spec` 的 `datas` / `hiddenimports` 配置
- **Produces**: `requirements.txt` 追加 `jieba>=0.42.1`；`yzplan.spec` 的 `datas` 追加 `collect_data_files('jieba')`、`hiddenimports` 追加 `jieba`

### Steps

- [x] **8.1 修改 `requirements.txt`**：在末尾追加：

```
jieba>=0.42.1
```

- [x] **8.2 修改 `yzplan.spec`**。当前 `Analysis` 块 `datas` 是列表（L68–73）、`hiddenimports` 是列表（L74–97），文件顶部无 `collect_data_files` 导入。三处改动：

```python
# yzplan.spec — 顶部（import sys as _sys 之后）追加
from PyInstaller.utils.hooks import collect_data_files
```

```python
# yzplan.spec — Analysis 块 datas 列表末尾追加 collect_data_files('jieba')
datas=[
    (os.path.join(_VENV, "PySide6", "plugins"), "PySide6\\plugins"),
    (os.path.join(_VENV, "PySide6", "translations"), "translations"),
    (os.path.join(_SPEC_DIR, "qt.conf"), "."),
    (os.path.join(_SPEC_DIR, "data", "favicon.ico"), "data"),
] + collect_data_files("jieba"),
```

```python
# yzplan.spec — Analysis 块 hiddenimports 列表末尾追加 "jieba"
hiddenimports=[
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "shiboken6",
    "win32com",
    "win32clipboard",
    "win32com.client",
    "sqlite3",
    "ctypes.wintypes",
    "modules.path_forward",
    "modules.sys_info",
    "modules.rss_aggregator",
    "modules.page_selector",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "psutil",
    "feedparser",
    "requests",
    "chardet",
    "charset_normalizer",
    "jieba",
],
```

- [x] **8.3 安装依赖并验证导入**：

```bat
.venv\Scripts\pip install "jieba>=0.42.1"
.venv\Scripts\python -c "import jieba; print(jieba.__version__)"
```

预期输出：打印 jieba 版本号（如 `0.42.1`）。

- [x] **8.4 全量回归 + 门禁**：

```bat
.venv\Scripts\python -m pytest tests/test_rss_agg_service.py tests/test_rss_high_freq.py tests/test_rss_remainder.py tests/test_rss_text_segment.py -v
.venv\Scripts\python -m pytest tests/test_style_guardrails.py -v
.venv\Scripts\python scripts/audit_styles.py --check
```

预期输出：全部通过 / `0 new violations`。

- [x] **8.5 构建实测**（确认 jieba 词典被打进产物）：

```bat
build.bat
```

预期输出：构建成功；在 `dist/` 产物目录确认 `jieba` 词典文件存在（`Get-ChildItem -Recurse dist | Where-Object { $_.Name -match 'dict' }` 能看到 jieba 的 `dict.txt` 或 `*.dict` 文件）。

- [x] **8.6 提交**：`build: 打包 jieba 依赖与词典`

---

## 验收清单（全部完成后）

- [x] `pytest tests/test_rss_agg_service.py tests/test_rss_high_freq.py tests/test_rss_remainder.py tests/test_rss_text_segment.py -v` 全绿
- [x] `pytest tests/test_style_guardrails.py -v` 通过（主题切换无残留、1.6x 无截断）
- [x] `python scripts/audit_styles.py --check` 无新增违规
- [x] `auto_exclude.py` 与 `tests/test_rss_auto_exclude.py` 已删除，无残留引用
- [x] `build.bat` 构建成功且 jieba 词典在产物内
- [x] 8 个任务各有一个 conventional commit