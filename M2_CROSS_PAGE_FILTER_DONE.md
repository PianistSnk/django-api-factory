# M2 Cross-Page Filter — DONE (2026-06-09)

> 接上次 `M2_FILTER_FIX_DONE.md`。修了 substring 误伤后，filter 还有一个根本问题：**只对当前页生效**。本批把 filter 改成 server-side 真正跨页。

## 问题

T2.1 (Jun 8) 改 server-side 分页后，admin 拿每页 50 条做 in-memory filter。
所以 `?userId=1&p=2` 拿的是 API 第 2 页（posts 51-100），然后 client-side filter 匹配 userId=1
→ 实际只能"看"每页 50 条里的 userId=1，**翻页就漏数据**。

> 100k 数据里 userId=1 有 10 条（id 1, 10001, 20001, ..., 90001），全部分散在 2000 页里。
> 老代码永远只能看到 1 条，剩 9 条要靠运气翻页。

## 修法

### 1. Mock server 加 server-side filter + `X-Total-Count`

`spikes/big-data-mock/server.py:do_GET` 加 filter 逻辑：

```python
filtered = DATA["posts"]
if userId:    filtered = [p for p in filtered if p["userId"] == int(userId)]
if title:     filtered = [p for p in filtered if p["title"] == title]
if body:      filtered = [p for p in filtered if p["body"] in body_filters]  # 多值 OR
if id:        filtered = [p for p in filtered if p["id"] == int(id)]
...
self.send_header("X-Total-Count", str(len(filtered)))
```

### 2. `Post.urls()` + `BigPost.urls()` 透传 filter kwargs

之前 `urls()` 把 `**kwargs` 丢掉。现在拼到 query string（用 `urllib.parse.quote` 编码）：

```python
qs_parts = [f"_page={page}", f"_limit={page_size}"]
for k, v in kwargs.items():
    if v is None or v == "":
        continue
    qs_parts.append(f"{k}={quote(str(v), safe='')}")
return base_url + "?" + "&".join(qs_parts)
```

### 3. Admin 读 `X-Total-Count` 覆盖 paginator total

`get_api_data` 读 response header 存到 `self._api_filtered_total`。
`get_paginator` 优先级：`_api_filtered_total` → `expected_total` → 0。

```python
total = (
    getattr(self, "_api_filtered_total", None)
    or getattr(self, "expected_total", None)
    or 0
)
```

### 4. Client-side filter 保留作 safety net

API 不支持 filter / 不返 X-Total-Count 时，client-side filter 还能工作（退化到旧行为）。
支持 filter 的 API，client-side 是 no-op（数据已被 API 过滤好）。

## 验证

| URL | 之前 (current page filter) | 现在 (server-side cross-page) |
|---|---|---|
| `?userId=1&p=1` | 1 行（userId 1 误伤修复后） | **10 行** (ids 1, 10001, 20001, ..., 90001) ✓ |
| `?userId=1&p=2` | 0 行 (page 2 是 posts 51-100, 没 userId=1) | **0 行** (server-side 真没 userId=1) ✓ |
| `?userId=99&p=1` | 0 行 | **10 行** (ids 99, 10099, ..., 90099) ✓ |
| Paginator | 2000 页 (`expected_total=100_000`) | **1 页** (X-Total-Count=10) ✓ |
| Post (jsonplaceholder) `?userId=1` | 同上 1 行 | **10 行**, 1 页 ✓ |

## 测试

`tests/test_pagination.py` 加 5 个新 test：
- `get_api_data` 读 `X-Total-Count` header
- `get_paginator` 优先用 `_api_filtered_total` 而不是 `expected_total`
- 无 header 时回退 `expected_total`
- `Post.urls()` 透传 `userId` / `title` kwargs
- `BigPost.urls()` 同上

**结果**：128 passed, 0 failed, coverage 71.82% ≥ 70% ✓

## 端到端（dev server 8141 + mock 8200）

```
=== ?userId=1 across all pages on 100k BigPost ===
  p=1:  rows=10 |  10 大数据 Post (M2 spike)
  p=2:  rows=0  |  10 大数据 Post (M2 spike)
  p=3:  rows=0  |  10 大数据 Post (M2 spike)
```

Server 8141 + mock 8200 仍开着，user 可直接 `http://127.0.0.1:8141/admin/api/bigpost/?userId=1&p=1` 验证。
