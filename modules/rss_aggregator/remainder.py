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
