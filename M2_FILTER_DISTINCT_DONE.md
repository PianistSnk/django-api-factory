# M2 Filter Distinct (跨页枚举值) — DONE (2026-06-09)

> 接 M2_CROSS_PAGE_FILTER_DONE.md。修了 filter URL 跨页之后, 还有一个 UI 痛点:
> **dropdown 只显示当页 200 个值** (从 100k 数据里挑的), 不是全部 10000 个 userId。

## 问题

T1.6 filter dropdown 用 `model_admin.json_to_filter` 灌值 — 那是当前 API 页 (200 行) 的数据。
所以 100k 数据 / 200 per page 时, **dropdown 只显示 200 个 userId**, 实际有 10000 个。

用户在浏览器看到:
- "userId (200)" 按钮 — 200 是当页的 200, 看着像只有 200 个
- 翻到 p=5 — dropdown 变成 201-250 (跟着 p 变)
- 想要 userId=5000 — 找不到, dropdown 没列

## 修法

### 1. Mock server 加 `/distinct?field=X` 端点

`spikes/big-data-mock/server.py:do_GET` 新分支:

```python
if self.path.startswith("/distinct"):
    field = qs.get("field")[0]
    distinct = sorted({p[field] for p in DATA["posts"] if field in p},
                     key=lambda x: (x is None, x))
    return {"field": field, "count": len(distinct), "values": distinct}
```

启动时数据已在内存, distinct 是 `O(N)` set → sort, 10w 行 1ms 不到。

### 2. Admin 加 `get_filter_choices()` hook

`src/django_api_factory/admin.py` 新增默认方法, 默认返回 None (legacy 路径)。

`BigPostAdmin` override:
```python
def get_filter_choices(self, field_name, request):
    cache_key = self._filter_distinct_cache_key(field_name)
    # Redis cache hit
    if self.filter_distinct_cache_ttl and self.cache_backend:
        cached = self.cache_backend.get(cache_key)
        if cached: return json.loads(cached)
    # Cache miss: call mock /distinct
    base = self.model.urls(page=1, page_size=1).split("/posts")[0]
    resp = requests.get(f"{base}/distinct?field={field_name}", timeout=5)
    data = resp.json()
    values = data.get("values", [])
    if self.filter_distinct_cache_ttl and self.cache_backend:
        self.cache_backend.set(cache_key, json.dumps(values), 300)
    return values
```

Redis 缓存 5min (filter_distinct_cache_ttl=300), per-model 不是 per-user (数据是同一份)。

### 3. `APIFilter.__init__` 用新 hook

`src/django_api_factory/filter.py`:
- 优先调 `model_admin.get_filter_choices(field_name, request)`
- 返回非空 → 用它
- 返回 None / 抛异常 / 没定义 → 回退 `json_to_filter` (legacy 行为, 旧 subclass 不破)

### 4. `BigPostAdmin.list_per_page = 200` (per user "200 条每页")

## 验证 (100k BigPost)

| | 之前 | 现在 |
|---|---|---|
| per_page default | 50 | **200** |
| userId dropdown | 200 (from page 1) | **10000** (全部) |
| title dropdown | 200 (from page 1) | **100000** (全部) |
| body dropdown | 200 (from page 1) | **100000** (全部) |
| filter label | "userId (200)" | "userId (10001)" (= 10000 + 1 All) |
| 跨页 userId=7777 (dropdown 之外的) | URL 手输仍 work | ✓ work |
| Redis cache | — | 3 keys (`distinct:api.bigpost:*`) |

## 测试

`tests/test_filter.py` 加 5 个新 test:
- `get_filter_choices` 提供时 dropdown 用它 (10000 values)
- 无 hook → 回退 json_to_filter (3 values)
- hook 返 None → 回退 json_to_filter
- hook 抛异常 → 回退 json_to_filter (不 crash changelist)
- `APIAdmin.get_filter_choices` 默认返 None (backwards compat)

**结果**: 133 passed, 0 failed, coverage 72.38% ≥ 70% ✓

## 端到端 (dev server 8141 + mock 8200)

```
=== 100k 数据 200/page ===
  per_page: 200 (default) ✓
  userId filter label: userId (10001)  (= 10000 + 1 "All")
  unique userId dropdown options: 10000
  title dropdown options: 100000
```

Server 8141 + mock 8200 仍开着, user 可直接 `http://127.0.0.1:8141/admin/api/bigpost/?p=1` 验证。

## 还能加

- **distinct 端点 limit**: 100k 全部 title 一行一行渲染慢, 加 `?limit=100&offset=0` 分页拉
- **Post/Coin 接 /distinct**: JSONPlaceholder / CoinGecko 没这端点, 暂用 legacy 路径
- **distinct counts**: `?field=userId` 可顺带返每个值的 count (例: `userId=1: 10 个`), UI 上更直观
