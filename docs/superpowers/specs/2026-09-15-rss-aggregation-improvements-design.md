# RSS 聚合改进设计规格

- **日期**：2026-09-15
- **状态**：设计已批准，待生成实现计划
- **涉及模块**：`modules/rss_aggregator`、`modules/rss_store`、`core/constants.py`、`requirements.txt`、`yzplan.spec`

---

## 1. 背景

RSS 聚合模块（`modules/rss_aggregator`）目前有两个痛点。

### 痛点 1 — 高频词面板对中文无效

`modules/rss_aggregator/text_utils.py:175` 的分词正则：

```python
_WORD_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+")
```

它把**一整串连续汉字当作一个 token**。像「海贼王第1000话高清下载」会被切成一个词，中文词频统计基本失效。

此外面板还有这些问题：

- 只出 **top 12**（`dialogs/builders.py:118` 的 `analyze_high_freq_titles(titles, top_n=12)`）；
- chips 只显示词本身，**不显示频次**；
- **仅「相似性」类型可见**（`dialogs/f.py:127-128`、`167-177`）；
- 标题来源硬上限 **200 条**（`aggregation_titles(limit=200)` / `recent(limit=200)`）；
- 停用词仅 **19 个硬编码**（`text_utils._STOP_WORDS`）。

### 痛点 2 —「未分类条目」用关键词模糊排除实现

`modules/rss_aggregator/auto_exclude.py` 取其他子聚合成员的标题，用 `_extract_keywords(..., top_n=20)` 提取高频词写进 `kw_forbidden`，于是「未分类」= 标题不含这些词的条目。后果：

- **误伤**：真正未分类、但标题恰好含某个高频词的条目被错误排除；
- **漏网**：已被某子聚合覆盖、但标题不含高频词的条目仍留在「未分类」里；
- **自引用漂移**：遍历子聚合时**未排除自身**，第二次同步起「未分类条目」自己的成员被算进「已覆盖」，其高频词反过来喂给自己的 `kw_forbidden`，逐轮漂移；
- **触发面过窄**：只在相似性类型父聚合刷新后联动（`agg_service.py:35`），且 `_refresh_one`（96 行）不判类型，两条路径行为不一致。

---

## 2. 目标

1. 用真实中文分词把「全部条目标题」汇成高频词表，供用户快速构建聚合条件。
2. 把「未分类条目」改为**精确集合补集**，保证「条目界面里已在其他子聚合出现过的内容，未分类条目里不得再出现」。
3. 围绕这两点补齐六项辅助能力（S1–S6）。

---

## 3. 非目标（YAGNI）

- 自动聚类生成子聚合（太魔法，用户不可控）
- 词云可视化
- 学习用户行为自动命名 / 自动调阈值
- 「移动到…」的 pinned（固定标记）机制 —— 见 6.2 的语义说明

---

## 4. 需求 A：中文分词高频词面板

### 4.1 分词引擎

**新文件 `modules/rss_aggregator/text_segment.py`**，依赖 `jieba`。

要点：

- **懒加载单例 + 线程锁**：模块级 `_jieba` 变量 + `threading.Lock`，首次调用才 `import jieba`。首次加载 0.5–1s，必须在**后台线程**完成，不阻塞 UI。
- **词性过滤**：用 `jieba.posseg.cut(title)`，只保留允许词性的词：
  - 保留：`n`（名词）、`nr` / `ns` / `nt` / `nz`（人名 / 地名 / 机构名 / 其他专名）、`eng`（英文）、`m`（数词，用于型号如 `1080` / `2160`）、`x`（非语素字，字母数字串）
  - 排除：`v` / `a` / `d` / `p` / `c` / `u` / `r` / `y` / `e` / `o` / `z` / `w`（动词 / 形容词 / 副词 / 介词 / 连词 / 助词 / 代词 / 语气词 / 叹词 / 拟声 / 状态词 / 标点）
- **过滤规则**：剔除长度 < 2 的纯 ASCII 词、纯数字词、以及停用词。
- **排序**：`Counter` 频次降序，同频保持首现顺序。
- **截断**：`top_n` 硬上限 **200**。
- **回退**：`import jieba` 失败时退回现有 `text_utils._WORD_RE` 正则分词，保证功能降级不崩。

对外接口：

```python
def segment_titles(titles, top_n=50, extra_stop_words=None) -> list[tuple[str, int]]
def available() -> bool                       # jieba 是否可用
DEFAULT_STOP_WORDS: frozenset[str]
```

### 4.2 停用词

- **存储**：`settings.json` → `rss.high_freq.stop_words`（`list[str]`），**只存用户自定义部分**。
- **生效**：每次分析时 `DEFAULT_STOP_WORDS ∪ 用户自定义` **取并集**。内置表可随版本演进自动生效，不需要用户迁移。
- **内置默认**：在现有 `text_utils._STOP_WORDS`（19 个）基础上扩充内容站常见噪声词（`下载` / `在线` / `高清` / `全集` / `最新` / `更新` / `资源` / `免费` / `字幕组` 等）。
- **编辑入口**：高频词面板上的「停用词…」按钮 → 新文件 `modules/rss_aggregator/dialogs/stop_words.py` 对话框；输入按 `[,，\s]+` 切分去重（复用 `text_utils._parse_keywords`）。

### 4.3 面板 UI

改动集中在 `dialogs/builders.py` 的 `build_high_freq_group`。

| 项 | 现状 | 目标 |
|---|---|---|
| 可见范围 | 仅 `similarity` | **所有聚合类型**（`remainder` 只读除外） |
| 数据源 | 父聚合标题上限 200 | 当前聚合**全部**条目标题，后台线程 |
| 数量 | 固定 top 12 | `QSpinBox`，默认 **50**，范围 10–**200** |
| chips 内容 | 只有词 | `词 · 频次` |
| 布局 | 单行 `_FlowLayout` | `_FlowLayout` 内嵌 `QScrollArea`，固定较高高度以**一次多显示** |
| 搜索 | 无 | 顶部 `QLineEdit` 子串过滤（不区分大小写） |
| 多选 | 无 | chips 支持 Ctrl / Shift 多选 → 批量「加入必须」 |
| 单击 | 加入【必须】 | 保留 |
| Shift+单击 | 加入【禁止】 | 保留 |
| 批量 | 无 | 「全部加入必须」按钮（作用于当前过滤后的 chips） |
| 清空 | 无 | 「清空关键词」按钮：清空三桶 → 全部词回池 |
| 停用词 | 19 个硬编码 | 「停用词…」按钮打开编辑对话框 |

**chips 池 ↔ 关键词桶联动（核心机制）**：

```
chips 池 ≡ 分析结果全集 − (【必须】∪【可选】∪【禁止】 三桶中已解析的词)
```

- 词被加入任一杯 → 立即从 chips 池移除；
- 从桶里删词 → 该词自动回到 chips 池；
- 「清空关键词」→ 一键还原全量；
- 分析结果缓存在内存（`dialog._hf_results`），渲染时用 `_parse_keywords` 解析三桶并做差集。

### 4.4 命中预览（S1）

- 聚合编辑对话框底部新增 `QLabel`：`当前条件命中 N 条`。
- 任何影响筛选条件的控件变化 → **300ms 防抖** → 后台线程执行一条 `COUNT(*)`（复用 `_keyword_clauses` 等价条件 + 成员 / 标签 scope）。
- 成员 / 标签 / 关键词 / 类型变化都触发重算。

---

## 5. 需求 B：未分类条目（精确集合补集）

### 5.1 新聚合类型 `remainder`

- `agg_type = "remainder"`，显示名「未分类条目」；类型标签表（`dialogs/f.py:13`）加一项。
- **仅由系统创建**：parent 模式类型下拉排除 `remainder`。
- **只读**：名称、类型、成员、关键词全部锁定；双击直接查看列表，不弹编辑对话框。
- **可删除 / 可禁用**（走侧边栏现有操作）。

### 5.2 成员算法

在 `modules/rss_store/store_aggregation.py` 的 `refresh_aggregation` 中新增 `remainder` 分支：

```
scope    = 父聚合快照（复用已有 parent_id 分支）
siblings = 同一父下、除自己以外的所有子聚合 id
最终     = scope
           AND i.hash NOT IN (兄弟成员 hash 并集)
           AND (i.torrent_hash = '' OR i.torrent_hash NOT IN (兄弟成员 torrent_hash 并集))
```

```sql
-- 排除 A：兄弟成员 hash 并集
i.hash NOT IN (
    SELECT hash FROM aggregation_items WHERE agg_id IN (兄弟ids)
)
-- 排除 B：兄弟成员 torrent_hash 并集（带空值豁免）
AND (
    i.torrent_hash = ''
    OR i.torrent_hash NOT IN (
        SELECT i2.torrent_hash FROM items i2
        JOIN aggregation_items ai ON ai.hash = i2.hash
        WHERE ai.agg_id IN (兄弟ids) AND i2.torrent_hash != ''
    )
)
```

**关键约束**：

- **排除 B 必须带 `torrent_hash = ''` 豁免**：非磁链条目本就没有 BTIH，不能因为「空值不在集合里」被误判。只对真正有 BTIH 的条目做**种子级去重**（解决「同一种子不同标题 → hash 不同 → 重复」）。
- **siblings 必须排除自身 id** —— 这是修掉现有 `auto_exclude.py` 自引用漂移 bug 的关键。
- 新增辅助方法 `sibling_aggregation_ids(parent_id, exclude_id)`。
- **不需要 schema 迁移**：`remainder` 只是 `agg_type` 的一个新取值，`aggregations` 表现有列完全够用，`_SCHEMA_VERSION` 保持 `4`。

### 5.3 生命周期

| 项 | 规则 |
|---|---|
| 创建条件 | 父聚合存在 **≥1 个其他子聚合**（`parent_id = 父id AND id != 自身`）时才创建；没有则跳过（不造噪音） |
| 触发时机 | 父聚合刷新后统一调用；`agg_service._refresh_for_feed_sync` 与 `_refresh_one` **两条路径行为一致**（去掉 similarity-only 判断） |
| 删除后 | 下次父聚合刷新**自动重建** |
| 剩余 0 条 | **仍然显示（0 条）**，不自动隐藏 |
| 排序 | `sort_order` 设极大值（`2147483647`），恒居子聚合列表末位 |
| 旧名迁移 | `{父名}未分类条目`、`{父名}_剩余` → 自动改名为「未分类条目」 |

### 5.4 废弃

- `modules/rss_aggregator/auto_exclude.py` **文件删除**；其职责由新文件 `modules/rss_aggregator/remainder.py` 取代。基于 `_extract_keywords` + `kw_forbidden` 的模糊排除逻辑整体废弃。
- 系统不再自动写入 `kw_forbidden`。

---

## 6. 辅助功能 S2–S6

### 6.1 S3 分类覆盖率

父聚合行显示 `未分类 12 / 240`（未分类条目数 / 父聚合总条目数），走现有侧边栏计数机制。

### 6.2 S2 一键派发

在「未分类条目」列表上，选中若干条后右键：

- **「用选中条目新建子聚合」**：取选中标题 → `segment_titles` 提取高频词 → 预填【必须】桶 → 打开 `_AddAggregationDialog`（`parent_id` = 该父聚合）。
- **「移动到…」**：弹出兄弟子聚合选择框 → 取选中标题的高频词，**并入目标聚合的【可选】桶**（`kw_optional`，OR 语义），随后刷新目标聚合。

> **语义说明（重要取舍）**：不采用「按 hash 写入 `aggregation_items`」的方案。原因是 `refresh_aggregation` 是 `DELETE` 后重建，手动写入的记录会被下次刷新冲掉，用户会看到「移过去的条目刷新后凭空消失」。
>
> 改用「并入【可选】关键词桶」后，目标聚合会在下次刷新时自然吸纳同类条目，且用户能在编辑框里看到关键词的变化，行为可预测。
>
> 代价：这是**泛化吸纳**而非**精确纳入** —— 若用户想要精确控制单条归属，应使用「用选中条目新建子聚合」。
>
> 曾评估「新增 `aggregation_pins` 表 + `refresh_aggregation` 重建后合并」的精确方案，因引入新表与额外刷新逻辑复杂度而**否决**。

- 闭环：未分类 → 分析高频词 → 建 / 并入子聚合 → 未分类自动收缩。

### 6.3 S4 相似性阈值实时预览

`spin_threshold` 拖动 → 防抖 → 后台跑聚类 → 显示 `阈值 0.55 → 8 簇 / 覆盖 63 条`。

### 6.4 S5 子聚合批量刷新

父聚合右键菜单「刷新全部子聚合」：一键 refresh 所有子聚合 + 重建未分类条目（`agg_service.refresh_subtree(parent_id)`）。

### 6.5 S6 刷新时间可见

侧边栏聚合行显示 `last_refreshed` 的相对时间（如「3 分钟前」）。

---

## 7. 配置

`core/constants.py` 的 `DEFAULT_CONFIG["rss"]` 新增：

```python
"high_freq": {"stop_words": []},
```

读写走 `core/config.py` 的 `AppConfig`（dot-path `get` / `set`，落盘 `data/settings.json`）。

---

## 8. 依赖与打包

- `requirements.txt` 新增 `jieba>=0.42.1`。
- `yzplan.spec`：`datas` 增加 `collect_data_files('jieba')`（词典 ~5MB）；`hiddenimports` 增加 `jieba`。
- 构建后需**实测一次**，确认词典被打进产物。

---

## 9. 测试策略

遵循项目 TDD 约定：先写失败测试，再实现。

**新增**

- `tests/test_rss_text_segment.py`：中文分词正确性 / 词性过滤 / `内置默认 ∪ 自定义` 停用词并集 / `top_n` 上限 200 / jieba 缺失时回退正则。
- `tests/test_rss_remainder.py`：hash + torrent_hash 双排除 / 空 BTIH 豁免 / 自引用消除（连续两次同步结果稳定）/ 空集仍创建 / 删除后重建 / 旧名迁移。

**更新**

- `tests/test_rss_agg_service.py`：触发逻辑断言（不再限于 similarity）。
- `tests/test_rss_high_freq.py`：chips 池补集、频次显示、搜索过滤、批量入桶。
- `tests/test_rss_auto_exclude.py`：**删除**（其覆盖的行为由新增的 `tests/test_rss_remainder.py` 取代）。

**门禁**

- `pytest tests/test_style_guardrails.py -v` 必须通过（新控件走 `ui/widgets.py` 工厂、颜色走 `theme_palette()`、尺寸走 `sizing()`）。
- `python scripts/audit_styles.py --check` 不得新增违规。

---

## 10. 风险与兼容

| 风险 | 缓解 |
|---|---|
| jieba 首次加载 0.5–1s 卡 UI | 懒加载 + 后台线程计算，UI 只接收结果 |
| PyInstaller 漏打包 jieba 词典 | spec 显式 `collect_data_files` + 构建后实测 |
| 用户手动建同名「未分类条目」 | 冲突检测：自动改名或提示 |
| `remainder` 与手动子聚合混排 | `sort_order` 极大值恒居末位 |
| 旧 `{父名}未分类条目` 残留 | 首次同步自动迁移改名 |
| 移除 `auto_exclude.py` 破坏现有测试 | 同步重写 `tests/test_rss_auto_exclude.py` |

---

## 11. 实施顺序（建议）

1. 数据层：`remainder` 分支 + `sibling_aggregation_ids`（含测试）。
2. `remainder.py` 取代 `auto_exclude.py` + 旧名迁移（含测试）。
3. `agg_service` 触发统一 + `refresh_subtree`（含测试）。
4. `text_segment.py` + 停用词配置（含测试）。
5. 高频词面板重写（chips 池 / 搜索 / 多选 / 停用词对话框）。
6. 命中预览 S1。
7. S2 / S3 / S4 / S5 / S6。
8. 依赖与 spec 打包改动 + 构建验证。
