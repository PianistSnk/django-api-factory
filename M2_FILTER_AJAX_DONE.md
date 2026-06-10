# M2 Filter AJAX (load more + search) — DONE (2026-06-09)

> 接 M2_FILTER_CAP_DONE.md。修了 cap=200 之后, dropdown 只 200 个值,
> 但用户搜不到 200 之外的值 (`?userId=7777` 不在 top 200 里)。
> **T1.6 那个 client-side 文本匹配只在 DOM 里 200 个搜** — 找不到 dropdown 之外的。

## 修法

### 1. Mock `/distinct?q=foo` — 服务端搜索

```python
q = (qs.get("q") or [""])[0].strip().lower()
distinct = sorted({p[field] for p in DATA["posts"] if field in p}, ...)
if q:
    distinct = [v for v in distinct if q in str(v).lower()]
# 然后照常 limit/offset
```

返回 `{values, count, truncated, q}` — `count` 是搜索后命中数, `truncated` 标志是否还有更多。

### 2. Admin `changelist_view` 短路 `?ajax_distinct=1`

```python
def changelist_view(self, request, extra_context=None):
    if request.GET.get("ajax_distinct") == "1":
        return self._ajax_distinct(request)
    return super().changelist_view(request, extra_context)

def _ajax_distinct(self, request):
    # 把 ?field=X&q=foo&offset=N&limit=200 转到 mock 的 /distinct
    # 返 JsonResponse
```

**注意**: 之前以为要新 URL pattern, 实际直接在 changelist_view 短路最干净 — 走同一份 auth, 不用动 urls.py。

### 3. Filter 模板加 `<button class="filter-inline-load-more">` + status span

```html
<ul class="filter-inline-list" data-offset="0" data-total="{{ spec.total_count|default:0 }}">
  ... <li> items ...
</ul>
<button class="filter-inline-load-more">加载更多…</button>
<span class="filter-inline-status"></span>
```

**踩坑**: Django 模板禁止 `_` 开头的属性, 写 `{{ spec._total_count }}` 抛
`TemplateSyntaxError: Variables and attributes may not begin with underscores`。
改用 `{{ spec.total_count }}`, Python 端同时存 `_total_count` (兼容老代码) 和 `total_count` (模板用)。

### 4. change_list.html JS: debounced search + load-more

- `input` 事件: 250ms debounce → AJAX `?q=<value>` → **replace** `<ul>` 内容
- `load-more` click: AJAX `?offset=N&limit=200` → **append** `<li>` 到 `<ul>`
- 两者共用 `fetchDistinct(input, q, offset, replace, btn)` helper
- Loading state: button 改 "加载中…", span 改 "搜索中…"
- 完成后: button 改 "加载更多…" (如果有更多) 或隐藏; span 改 "匹配 N 个 (已显 M)"

## 端到端实测 (100k BigPost)

| | 结果 |
|---|---|
| 页面 cold | 195KB / 170ms |
| `?ajax_distinct=1&field=userId&limit=3` | `{count:10000, returned:3, truncated:true, values:[1,2,3]}` |
| `?ajax_distinct=1&field=userId&q=7777` | `{count:1, returned:1, values:[7777]}` ✓ 找到 top 200 之外 |
| `?ajax_distinct=1&field=userId&q=1&offset=20` | `{count:3440, returned:3, values:[101,102,103]}` ✓ 翻页 |
| Load more 按钮 | 渲染 (display:none 初始, DOMContentLoaded JS 显) |
| 搜索 debounce | 250ms |

## 跟之前比

- **旧**: T1.6 client-side hide/show, 只在 DOM 里 200 个搜 — top 200 之外找不到
- **新**: server-side search via AJAX, top 200 之外能搜, 还能 load more 翻页

## 踩过的坑 (教训)

1. **`{# #}` 是单行注释** (SOUL.md 红线, 我又踩了) — 多行原样输出到 HTML, 模板语法错
   导致整个 filter 块被当字符串 render, 浏览器看到的就是 raw template
2. **Django 模板禁止 `_` 开头属性** — `{{ spec._total_count }}` 抛
   `TemplateSyntaxError`. 必须用 `total_count` (无下划线) + Python 端存两份
3. **T1.6 client-side 搜索不够用** — 只在 200 个 DOM 里搜, 真值找不到。要做搜索必须 server-side

## 测试 (3 个新 test)

- `changelist_view` 返 JSON 当 `?ajax_distinct=1`
- `?q=foo` 透传到 mock /distinct
- `APIFilter.total_count` 属性 (模板可访问, 无下划线)

**结果**: 140 passed, 0 failed, coverage 72.68% ≥ 70% ✓

## 还能加 (留作以后)

- **搜索高亮** — span 里把匹配部分加 `<mark>`
- **server-side sort** — `?sort=-count` 按出现频率排 (现在按 value 字典序)
- **键盘导航** — ↑↓ 选 + Enter 应用
- **cache-key 包含 q** — 不同 search term 各自 cache (避免同 key 串)
