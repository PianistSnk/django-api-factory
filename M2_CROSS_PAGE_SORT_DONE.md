# M2 Cross-Page Sort — Server-Side Sorting (2026-06-10)

> 接 M2_FILTER_PERF_DONE.md。修完 filter 跨页之后,还差最后一块: **sort 也是当页 sort**。
> 用户报告:"排序时候仍是当页排序,我要的是全量排序"。

## 问题

修完跨页 filter 之后,filter dropdown 跨页正确,但**点击列头排序**仍是当页:
- Page 1 按 `?o=-1.0` (id DESC) 内存 sort → 看到 50 条按 id desc 排
- 翻到 Page 2 → 又是 50 条按 id desc 排(内存 sort)
- **Page 1 跟 Page 2 之间没顺序保证** — server 返未排序的 50 条,client 内存 sort 没"全量"概念

**根因 1 (framework)**:`get_api_data` 把 Django admin 的 `?o=1.0,-2.0` 翻译成 `sort_keys` /
`sort_orders` 后**只在内存对当前页 50 条 sort** (line 1052-1110 `data = sorted(data, ...)`)。
**没透传给 server**。

**根因 2 (framework)**:API 支持 sort (jsonplaceholder + 我们的 mock server 都支持
`?_sort=<field>&_order=<asc|desc>`),但 framework 不知道透传。

**根因 3 (framework, hidden)**:framework 之前 `o` 解析在 `if self.actions:` 里面 —
没 actions 的 admin (BigPostAdmin, CoinAdmin) 跳过整段 col-idx → field 翻译,导致
`order_list` 仍是 `["-1", "0"]` 这样的 raw 拆解结果,后续 sort 全部错位 (col 1 vs field 0
offset bug)。

## 修法

### 1. mock server 加 server-side sort (`spikes/big-data-mock/server.py`)

在 filter 之后、pagination 之前 sort:
```python
sort_field = _first("_sort", _first("sort", None))
sort_order = _first("_order", _first("order", "asc")).lower()
if sort_field and sort_field in ("id", "userId", "title", "body"):
    reverse = sort_order == "desc"
    def _sort_key(p):
        v = p.get(sort_field)
        if v is None: return (1, "")
        if isinstance(v, (int, float)): return (0, v)
        return (0, str(v).lower())
    filtered = sorted(filtered, key=_sort_key, reverse=reverse)
```

接受 `_sort` / `_order` (jsonplaceholder-style) 也接受 `sort` / `order` (一些真 API 风格),
None 值放最后 (per SQL `NULLS LAST` convention),string 列 case-insensitive 排。

### 2. framework `get_api_data` 透传 sort (`src/django_api_factory/admin.py`)

新逻辑在 `get_api_data` 起点,把 **第一个 sort key** 翻译成 `_sort` / `_order` 加到
`paras` (在 fetch 之前)。冷启动 (第一次请求) `self.api_list` 还是 None,跳过 server-side
sort 走原 client-side sort 路径 — 边界安全。

```python
if order_list and getattr(self, "api_list", None):
    first = order_list[0]
    if first in ("id", "-id"):
        sort_field, sort_dir = "id", "desc" if first.startswith("-") else "asc"
    else:
        idx = abs(int(first))      # 注意: framework 已把 col idx 翻译成 fields idx
        if idx < len(self.api_list):
            sort_field = self.api_list[idx]
            sort_dir = "desc" if first.startswith("-") else "asc"
    if sort_field:
        paras["_sort"] = sort_field
        paras["_order"] = sort_dir
```

### 3. framework 把 `if self.actions:` 翻译移出 (Jun 2026 fix)

**Bug**:framework 之前把 col-idx → field 翻译 gate 在 `if self.actions:` 里面。BigPostAdmin
没 actions → 翻译跳过 → `order_list` 仍是 raw `["-1", "0"]` → 我新加的 server-side
sort 读 `order_list[0] = "-1"`,int("-1")=1 当 field 数组下标,field[1]="title",URL
变成 `_sort=title` (错的)。

修法:把那段 for 循环移出 `if self.actions:` 让它无条件执行。client-side sort 也连带
修对(action-less admin 之前是 silent no-op pass for unknown idx,排序结果跟 col idx 错位)。

### 4. framework reserved set 加 `_sort` / `_order` (silent filter bug)

**Bug**:framework `get_api_data` line 1191 之后用 `search_pars` 过滤 data (per-field
match),reserved set 包含 `o` / `p` 等 Django admin 内部 param,但**不含 `_sort` /
`_order` / `sort` / `order`**。我加的 `_sort=id&_order=desc` 进 paras 后被 framework
当作 filter field 遍历每个 item → `item["_sort"]` 永远 None → `field_matches = False` →
**0 rows**。

修法:reserved set 加 `_sort` / `_order` / `sort` / `order`。

## 验证

实测 (Django test client force_login):

### post/ (jsonplaceholder 100)

| URL | 期望 | 实测 page 1 ids |
|---|---|---|
| `?o=1.0` | id ASC | `1, 2, 3, 4, 5` ✓ |
| `?o=-1.0` | id DESC | `100, 99, 98, 97, 96` ✓ |
| `?o=2.0` | userId ASC | `1-5` (全 userId=1) ✓ |
| `?o=-2.0` | userId DESC | `91-95` (全 userId=10) ✓ |

### bigpost/ (100k mock) 跨页连续

| URL | p1 | p2 | p3 |
|---|---|---|---|
| `?o=1.0` | `1, 2, 3` | `201, 202, 203` | `401, 402, 403` ✓ |
| `?o=-1.0` | `100000, 99999, 99998` | `99800, 99799, 99798` | `99600, 99599, 99598` ✓ |
| `?o=2.0` | `1, 10001, 20001` | `21, 10021, 20021` | `41, 10041, 20041` ✓ |
| `?o=-2.0` | `10000, 20000, 30000` | `9980, 19980, 29980` | `9960, 19960, 29960` ✓ |

**跨页顺序保证** — 之前 page 1 跟 page 2 之间是断的,现在 server sort 后 page 1 末条跟
page 2 首条**严格连续**。

## 限制 / Trade-off

- **多字段 sort** (`?o=1.0,2.0`):framework 只翻译第一个 key,后续字段走 client-side
  sort 当前页。如果 API 支持多字段 sort (jsonplaceholder 接受 `_sort` 但不真做多字段
  排序),可后续扩展。
- **冷启动**:第一次请求 `self.api_list` 是 None,framework 跳过 server-side sort 走
  client-side 内存 sort 当前页。第二次开始 work。
- **client-side sort 仍保留**:作为 fallback。API 不支持 sort 时,UI sort 仍能 work
  (只当页,跟之前一样)。

## 改的文件

- `spikes/big-data-mock/server.py`:加 `_sort` / `_order` 处理 (11 行)
- `src/django_api_factory/admin.py`:
  - `o` 解析移出 `if self.actions:` gate (Jun 2026 fix)
  - 新加 server-side sort 翻译逻辑 (line ~1014-1043)
  - reserved set 加 `_sort` / `_order` / `sort` / `order` (line ~1197-1202)

## 测试

142 passed / 72.83% 覆盖率 (持平)。冷启动 + 多页跨页连续性手测验证。