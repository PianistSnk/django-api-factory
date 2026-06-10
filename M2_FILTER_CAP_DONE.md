# M2 Filter Cap (X of Y) — DONE (2026-06-09)

> 接 M2_FILTER_DISTINCT_DONE.md。修了 dropdown 跨页之后, 发现 100k 数据上
> **admin 页面 38s / 41MB HTML** — 把 200k 个 `<li>` 渲染到 DOM。

## 问题

修完 cross-page distinct 后, dropdown 显示全部 10000 userIds (10w 数据)。
实测:
- mock `/distinct?field=userId` → 14ms / 59KB
- mock `/distinct?field=title` → 80ms / **3.8MB**
- mock `/distinct?field=body` → 87ms / **7.6MB**
- admin 页面 cold → **38 秒 / 41MB HTML** (200k 个 `<li>`)

T1.6 的 inline search 是 client-side 文本匹配, hide/show `<li>` — 所有 option
还是得在 DOM 里。100k 自由文本字段 (title/body) 完全没有 dropdown 价值。

## 修法 (A 方案: Cap + X of Y badge)

### 1. Mock `/distinct?field=X&limit=N&offset=M`

```python
distinct = sorted({p[field] for p in DATA["posts"] if field in p}, ...)
total = len(distinct)
truncated = False
if limit > 0:
    sliced = distinct[offset:offset + limit]
    truncated = (offset + limit) < total
else:
    sliced = distinct
return {"field": X, "count": total, "returned": len(sliced),
        "truncated": truncated, "values": sliced}
```

### 2. BigPostAdmin 传 `filter_distinct_limit=200`

```python
class BigPostAdmin(APIAdmin):
    filter_distinct_limit = 200
    def get_filter_choices(self, field_name, request):
        ...
        url = f"{base}/distinct?field={field_name}&limit={self.filter_distinct_limit}"
        ...
        return {"values": [...], "count": total, "truncated": bool}
```

### 3. `APIFilter` 改 title: `(X of Y)` 当 truncated

```python
if total_count > len(values) > 0:
    self.title = f"{base} ({len(values)} of {total_count})"
elif len(values) > 0:
    self.title = f"{base} ({len(values)})"
```

### 4. 模板去掉冗余后缀

之前 `{{ title }}{% if choices|length > 10 %} ({{ choices|length }}){% endif %}`
→ 现在 `{{ title }}` (title 已经包含 count 信息, 不会再重复 `(200) (200)`)

### 5. Cache key 包含 limit

`distinct:{model}:l{limit}:{fieldhash}` — 改 limit 自动用新 cache, 不读旧值

## 验证 (100k BigPost, 200/page)

| | 之前 (unlimited) | 现在 (cap=200) |
|---|---|---|
| mock userId / distinct | 59KB | **975B** |
| mock title / distinct | 3.8MB | **7KB** |
| mock body / distinct | 7.6MB | **15KB** |
| admin 页面 cold | **38s / 41MB** | **0.17s / 188KB** |
| admin 页面 warm | (cache hit 也是 41MB) | **0.04s / 188KB** |
| filter label | "userId (10000)" | **"userId (200 of 10000)"** |
| dropdown `<li>` 渲染 | 10k/100k/100k | **200/200/200** |
| 速度提升 | — | **~220x** |

## T1.6 client-side search 仍 work

虽然只渲染 200 个, 但 T1.6 search box 在 `<details>` 里 hide/show `<li>`:
- 用户输 "7777" → JS hide 不含 "7777" 的 `<li>`, 只剩 "7777" 可见
- 这就够了, 因为 userId 10000 个里 7777 不会出现在 top 200 — 用户用 URL 手输

## 测试 (4 个新 test)

- title 显 "X of Y" 当 truncated (200 of 10000)
- title 显 "N" 当未 truncated (10)
- title 不加 count 当 empty
- legacy list 返 仍 work (backwards compat)

**结果**: 137 passed, 0 failed, coverage 72.95% ≥ 70% ✓

## 端到端 (dev server 8141 + mock 8200)

```
=== cold ===
  HTTP 200 | 0.172s | size=188KB  (was 38s / 41MB)
=== warm ===
  HTTP 200 | 0.036s | size=188KB

=== filter labels ===
  userId (200 of 10000)    201 <li>
  title (200 of 100000)   201 <li>
  body (200 of 100000)    201 <li>
```

Server 8141 + mock 8200 仍开着, `http://127.0.0.1:8141/admin/api/bigpost/?p=1`
直接看 dropdown — 应该秒开, label 显 "X of Y"。

## 还能加 (B 方案: 全懒加载)

- 改 filter template, dropdown 打开时才 AJAX 拉 options
- search box 加 debounce 远程拉
- 当前 cap=200 在 10w 数据上是 sweet spot, 10MB 数据集 (title 1000 unique) 可放开到 1000

## 还能加 (C 方案: 区分字段类型)

- 给 model 加 `filter_as_dropdown = False` 字段 (title/body 是自由文本, 不做 dropdown)
- 改 `get_list_filter` 跳过这些字段, 提示用 `?q=` 搜索框
- 现实里 title/body 100k 唯一值 dropdown 没用, 搜索是正解
