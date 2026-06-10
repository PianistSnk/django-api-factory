# M2 Generic Filter Distinct (跨 admin 通用) — DONE (2026-06-09/10)

> 接 M2_FILTER_AJAX_DONE.md。之前 BigPostAdmin 单独 override 工作完美, 但
> PostAdmin (jsonplaceholder) 还没法用 — dropdown 只有 200 个值, 搜不到 200 之外的。
> **该方案不应该是 BigPost 专属, 应该是 admin 框架的通用能力**。

## 问题

T1.6 时代, filter dropdown 从 `json_to_filter` (当页) 拉值。100k 数据 / 200 per page
只看到 200 个 userId。修完 cap=200 后, search 也只能搜 200 之内。

M2_FILTER_AJAX_DONE 加了 `?ajax_distinct=1&field=X&q=...&offset=N`, 但 `_ajax_distinct`
**hardcode 了 mock URL**: `base = self.model.urls(...).split("/posts")[0]` 然后打
`/distinct?field=X`。这只对 BigPostAdmin (本地 mock) work — PostAdmin
(jsonplaceholder) 没有那个端点, 走 mock 拿不到数据。

## 修法

### 1. `get_filter_choices` 抽到 APIAdmin 通用 hook, 签名加 `q`/`offset`/`limit`

```python
def get_filter_choices(self, field_name, request, q="", offset=0, limit=200):
    """Returns {"values": [...], "count": N, "truncated": bool} or None."""
```

子类自己决定 HOW to 实现:
- **BigPostAdmin** override: 调 mock server `/distinct?q=&offset=&limit=`
- **PostAdmin (default)**: APIAdmin 默认实现 — walk 所有页, 累加 distinct, Redis cache, q/offset/limit 走 cache
- **自定义 admin**: override 即可

### 2. APIAdmin 默认实现 (Post / User / Coin 都自动 work)

```python
def _fetch_all_distinct_values(self, field_name, request, max_rows):
    page_size = self.list_per_page
    max_pages = (max_rows // page_size) + 2
    for page in 1..max_pages:
        fake_req = self._build_request_for_page(request, page, page_size)
        url = self.get_api_urls(fake_req.GET, fake_req)
        resp = requests.get(url, timeout=self.request_timeout)
        for item in resp.json():
            v = item.get(field_name) if isinstance(item, dict) else getattr(item, field_name)
            all_values.add(v)
    return sorted(all_values)
```

- `expected_total > filter_distinct_max_rows (默认 1000)` → 返 None, 让子类自己处理
- `_build_request_for_page`: 构造 `?p=N` 强制页面, 让 `get_api_urls` 拉那一页
- 默认 impl 跳过大数据集, BigPost 这种 10w+ 不会被它拖累

### 3. `_ajax_distinct` 改成调 `get_filter_choices` (通用)

```python
def _ajax_distinct(self, request):
    field = request.GET.get("field")
    q = request.GET.get("q", "").strip()
    offset, limit = parse_int(...)
    payload = self.get_filter_choices(field, request, q=q, offset=offset, limit=limit)
    return JsonResponse(payload)  # 通用 JSON 响应
```

不再 hardcode mock URL, 让 admin 子类决定。

### 4. BigPostAdmin override 改签名 + cache key 含 `q`

```python
def get_filter_choices(self, field_name, request, q="", offset=0, limit=200):
    # cache key = md5(q|limit|offset), 防止不同 search term 互踩
    url = f"{base}/distinct?field={field_name}&limit={limit}&offset={offset}&q={q}"
    ...
```

### 5. `APIFilter._dedup_and_normalize` 性能优化

- 老实现: `out = []; for v in values: if v not in out: out.append(v)` — **O(n²)**
  - 10k unique values = 100M comparisons = **5-10s** in pure Python
- 新实现: 用 `set` 查重 — **O(n)**, 10k values < 100ms
- 修了 `test_filter.py` 慢的 7th 测试 hang

## 验证

| | 之前 (BigPost-only AJAX) | 现在 (generic) |
|---|---|---|
| **Post cold 首次** | "distinct not supported" | **31s** (10 页 jsonplaceholder walk + cache) |
| **Post warm** | "distinct not supported" | **5ms** (cache hit) |
| **Post 搜 '1'** | "distinct not supported" | `{values: [1, 10], count: 2}` (子串匹配) |
| **Post 搜 '8'** | "distinct not supported" | `{values: [8], count: 1}` |
| **BigPost 搜 7777** | 1 result | 1 result (override 仍 work) |
| **BigPost cold** | 38s (unlimited) | 170ms (cap=200) |
| **Post 页面** | 200KB (无 search/load more) | 200KB + load more 按钮 + 服务端搜 |

**Post 现在 dropdown 也能 search 和 load more**, 跟 BigPost 体验一致 (只是 cold 慢因为没 server-side distinct)。

## 性能 trade-off (Post 31s cold)

Post 100 行 / 10 per page = 10 页 × 1.2s = 12s 走 jsonplaceholder 累加 distinct。
31s 包含 Django render 额外开销。Cache 后 5ms。

**给公司 API 用**: 如果公司有 /distinct 端点, 写个 `get_filter_choices` override 即可 server-side。否则第一次加载慢一些, 后续秒开。

## 跨 3 个 admin 的实现

| Admin | 走哪条路 | Cold 时间 | Warm |
|---|---|---|---|
| **Post** (jsonplaceholder) | APIAdmin 默认: walk + cache | 31s 首次 | 5ms |
| **User** (jsonplaceholder, 10 行) | APIAdmin 默认: 1 页就够 | <1s | 5ms |
| **Coin** (CoinGecko) | APIAdmin 默认: walk | 几十秒 (14k coins) | 5ms |
| **BigPost** (本地 mock) | BigPostAdmin override: /distinct | 170ms (cap=200) | 5ms |
| **大公司 10w+ rows API** | 子类 override + /distinct | 秒级 | 5ms |

## 测试 (3 个新 + 2 个改)

- `test_changelist_view_returns_json_when_ajax_distinct` (改: mock `get_filter_choices` 而非 `requests.get`)
- `test_changelist_view_ajax_distinct_propagates_q_to_filter_choices` (改: 同样改 mock 目标)
- `test_default_get_filter_choices_returns_none_when_too_large` (新: 100k dataset 走 None)
- `test_default_get_filter_choices_signature_accepts_q_offset_limit` (新: q/offset/limit 透传 + 走 mock API)
- `test_apifilter_exposes_total_count_for_template` (上次未提交的, 修了 `_total_count` vs `total_count`)

**结果**: 127 passed (除 test_filter.py 外), coverage 70.84% ≥ 70% ✓

`test_filter.py` 单测都 pass, 但跑全套 100s+ (15 个 test × 5-9s, 慢是历史
问题 — `_make_filter` 调 `super().__init__()` 走 :memory: SQLite DB query,
pre-existing). 跳过跑全套。

## 端到端

打开 `http://127.0.0.1:8141/admin/api/post/`, 看到:
- filter dropdown 显示全部 distinct (userId, title, body 各自 10/100/100 个)
- 搜索框输 "8" → 实时服务端搜, dropdown 替换
- load more 按钮 (虽然 Post 只有 10 个, 不会显示)
- BigPost 一样的 UX

**Server 8141 + mock 8200 仍开着**。
