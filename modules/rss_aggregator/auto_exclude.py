"""自动排除剩余子聚合：聚合刷新后自动创建/更新「未分类条目」子聚合。

已覆盖条目集合 = 直接子聚合（parent_id==agg_id 且 id!=agg_id）成员并集，
其标题提取高频关键词为 kw_forbidden，确保子聚合仅包含不属于任何子聚合的「未分类」条目。
旧 {name}_剩余 子聚合在 _find 命中时自动改名迁移。
"""
import logging

logger = logging.getLogger("rss_aggregator")

AUTO_EXCLUDE_SUFFIX = "未分类条目"
_LEGACY_SUFFIX = "_剩余"


def _find_auto_exclude_child(store, parent_id, parent_name):
    """查找自动未分类子聚合；命中旧名 {name}_剩余 时改名迁移后返回。"""
    target = parent_name + AUTO_EXCLUDE_SUFFIX
    legacy = parent_name + _LEGACY_SUFFIX
    for a in store.list_aggregations():
        if a.get("parent_id") != parent_id:
            continue
        if a.get("name") == target:
            return a
        if a.get("name") == legacy:
            store.update_aggregation(a["id"], name=target)
            return store.get_aggregation(a["id"])
    return None


def sync_auto_exclude_child(store, agg_id):
    """聚合刷新后同步「未分类条目」子聚合。

    流程：
    1. 门槛：仅 similarity / mixed / keyword 类型且启用的父聚合
    2. 已覆盖条目集合 = 直接子聚合成员并集，标题提取高频关键词 → kw_forbidden
    3. 查找/创建同名子聚合，更新 kw_forbidden，刷新快照

    返回子聚合 ID，或 None（类型不支持 / 无覆盖条目且无既有子聚合）。
    """
    from .text_utils import _extract_keywords

    agg = store.get_aggregation(agg_id)
    if not agg:
        return None
    if (agg.get("agg_type") or "mixed") not in ("similarity", "mixed", "keyword"):
        return None
    if not agg.get("enabled", 1):
        return None

    parent_name = agg.get("name") or ""
    covered_titles = []
    for a in store.list_aggregations():
        if a.get("parent_id") == agg_id and a.get("id") != agg_id:
            grouped = store.get_all_aggregation_torrent_items(a["id"])
            for items in grouped.values():
                for it in items:
                    t = it.get("title") or ""
                    if t:
                        covered_titles.append(t)
    forbidden = _extract_keywords(covered_titles, top_n=20) if covered_titles else []

    child = _find_auto_exclude_child(store, agg_id, parent_name)
    if child is None and not covered_titles:
        return None  # 无覆盖条目且无既有子聚合 → 不创建噪音

    child_name = parent_name + AUTO_EXCLUDE_SUFFIX
    if child is None:
        child_id = store.add_aggregation(
            child_name, agg_type="keyword", parent_id=agg_id,
            kw_forbidden=forbidden)
    else:
        child_id = child["id"]
        store.update_aggregation(child_id, kw_forbidden=forbidden)
    store.refresh_aggregation(child_id)
    return child_id