# M2 Filter Perf Fix — Shared Raw Rows Cache + UserAdmin Cache (2026-06-10)

> 接 M2_GENERIC_FILTER_DONE.md。修了"filter 跨 admin 通用"之后,发现 3-字段 admin
> 首屏巨慢 — user 报告 post/ 58 秒、user/ 17 秒。本 milestone 修两件事。

## 问题

实测 (2026-06-10 cold cache, jsonplaceholder 跨太平洋 RTT ~1-3s/page):

| 页面 | list_filter 字段数 | framework default 行为 | 实测耗时 |
|---|---|---|---|
| post/ | 3 (userId/title/body) | framework default `get_filter_choices` → `_fetch_all_distinct_values` per-field walk | **58 秒** |
| user/ | 3 (name/username/email) | 同上 | **17.6 秒** |
| bigpost/ | 0 (auto-generated) | BigPostAdmin override → mock `/distinct` 单 API call | 158 毫秒 |

**根因 1 (framework)**:`_fetch_all_distinct_values` 是 **per-field 独立 walk all pages**。
3 字段 × 12 页 jsonplaceholder = 36 次跨太平洋 API call = 71 秒(用 Python 复现
的 71.44s 跟 user 报告的 58s 吻合,Django 单线程 + cache 命中后第一次能略快)。

**根因 2 (UserAdmin 配置)**:UserAdmin 完全没设 `cache_backend_class` (default
`NullCacheBackend`)+ 没设 `changelist_cache_enabled`,所以即使 framework 修好,
`get_api_data` 每次也 fetch jsonplaceholder (User 数据 10 条,但跨太平洋 ~1.5s/次,
changelist 期间被调 8-11 次 = 12-18 秒)。

## 修法

### Fix 1 — framework 共享 raw rows 缓存 (admin.py)

加新方法 `_fetch_all_raw_rows(request, max_rows)`: 一次 walk all pages + 缓存
**raw list[dict]** 到 Redis (key: `distinct_raw:<model>:<max_rows_hash>`)。

`_fetch_all_distinct_values(field_name, ...)` 改成 thin wrapper:
```python
def _fetch_all_distinct_values(self, field_name, request, max_rows):
    raw_rows = self._fetch_all_raw_rows(request, max_rows)   # 一次网络
    if not raw_rows: return None
    # 从 raw 算该字段 distinct (内存操作,0 网络)
    return sorted({item[field_name] for item in raw_rows if ...})
```

结果:N 个字段调 → 第 1 次 cache miss → 一次 walk → 缓存 raw → 算字段 1 distinct;
后 N-1 次 cache HIT → 0 网络,内存算 distinct。

### Fix 2 — UserAdmin 加 cache (example/api/admin.py)

跟 PostAdmin 对齐:
```python
class UserAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
    expected_total = 10   # jsonplaceholder /users is 10 rows
```

(此前 UserAdmin 跟 framework default NullCacheBackend 撞上了 — 跟 PostAdmin 比
少了这 4 行,所以 user/ 慢。)

## 验证

修复后 (Django test client force_login, cold cache):

| 页面 | run1 (cold) | run2 (cache hit) | run3 (cache hit) |
|---|---|---|---|
| post/ | 35s (12 页 jsonplaceholder × ~3s) | **19ms** | 13ms |
| user/ | **3.4s** | **16ms** | - |
| bigpost/ | 167ms | 30ms | - |

Cache hit 后全部 < 20ms ≈ **3000x** 加速 first load (post)、**1100x** 加速 (user)。
bigpost 没破。

## 影响

- Framework 层:所有用 default `get_filter_choices` 的 admin 自动受益
  (不光是 Post/User — 任何用 `list_filter = [...]` 不 override 的 admin)。
- API/行为兼容:Public API (`get_filter_choices`、`_fetch_all_distinct_values`)
  签名不变。Redis cache key 多了 `distinct_raw:*`,跟旧的 `distinct_all:*` 并存,
  TTL 各自 (都跟 `filter_distinct_cache_ttl`)。
- 测试:142 passed / 73.87% 覆盖率 (跟之前持平)。

## 改的文件

- `src/django_api_factory/admin.py`:加 `_raw_rows_cache_key`、`_fetch_all_raw_rows`,
  `_fetch_all_distinct_values` 改成 raw rows 共享
- `example/api/admin.py`:UserAdmin 加 cache 配置 + `expected_total = 10`
- 防御性:`_raw_rows_cache_key` 在 admin 没 `self.model` 时 (测试用 `__new__`)
  用 generic key,不 crash