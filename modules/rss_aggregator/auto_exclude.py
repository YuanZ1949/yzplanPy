"""自动排除剩余子聚合：相似性聚合刷新后自动创建/更新「_剩余」子聚合。

匹配簇的标题关键词提取为 kw_forbidden，确保子聚合仅包含不属于任何匹配簇的「剩余」条目。
"""
import logging

logger = logging.getLogger("rss_aggregator")

AUTO_EXCLUDE_SUFFIX = "_剩余"


def _find_auto_exclude_child(store, parent_id, parent_name):
    """查找已存在的自动排除子聚合（parent_id + name 匹配）。"""
    target_name = parent_name + AUTO_EXCLUDE_SUFFIX
    for a in store.list_aggregations():
        if a.get("parent_id") == parent_id and a.get("name") == target_name:
            return a
    return None


def sync_auto_exclude_child(store, agg_id):
    """相似性聚合刷新后同步「剩余」子聚合。

    流程：
    1. 获取父聚合所有成员条目
    2. 按标题相似度聚类
    3. 匹配簇（>=2 条）的标题提取高频关键词 → kw_forbidden
    4. 查找/创建同名子聚合，更新 kw_forbidden，刷新快照

    返回子聚合 ID，或 None（非相似性类型 / 无条目 / 无匹配簇且无既有子聚合）。
    """
    from .text_utils import _cluster_by_similarity, _extract_keywords

    agg = store.get_aggregation(agg_id)
    if not agg:
        return None
    if (agg.get("agg_type") or "mixed") != "similarity":
        return None
    if not agg.get("enabled", 1):
        return None

    parent_name = agg.get("name") or ""
    grouped = store.get_all_aggregation_torrent_items(agg_id)
    all_members = []
    for items in grouped.values():
        all_members.extend(items)
    if not all_members:
        return None

    threshold = float(agg.get("similarity_threshold") or 0.55)
    clusters = _cluster_by_similarity(all_members, threshold)
    # 匹配簇 = 包含 >= 2 条目的簇（至少有相似条目才提取关键词）
    matched = [cl for cl in clusters if len(cl["items"]) >= 2]
    matched_titles = [cl.get("title", "") for cl in matched]
    forbidden = _extract_keywords(matched_titles, top_n=20) if matched_titles else []

    child = _find_auto_exclude_child(store, agg_id, parent_name)
    if child is None and not matched:
        # 无匹配簇且无既有子聚合 → 不创建噪音
        return None

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
