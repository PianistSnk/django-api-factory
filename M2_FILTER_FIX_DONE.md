# M2 + Filter 修复 — DONE (2026-06-09)

> 上一份 `M2_T2.1_F1_DONE.md` (Jun 8 16:55) 之后的所有工作**没 commit**过 — git 里只有 T1.6.6 (81e2866) + T1.6+ CoinGecko (43e8cfa)。本批 commit 重新落盘。

## 1. 找回 M2/T2.1 spike 代码

`spikes/big-data-mock/` + `BigPost`/`BigPostAdmin` + 100k 行 mock server (port 8200)。

来源：`~/Documents/django-api-factory-snapshots/2026-06-08_get-object-fix-snapshot.tar.gz` (Jun 8 17:58，最后一份完整 snapshot)。

**关键配置**：
- `BigPostAdmin.expected_total = 100_000` + `list_filter = []`（auto-generate）
- `BigPost.urls()` → `http://127.0.0.1:8200/posts?_page=N&_limit=M`
- mock server: `.venv/bin/python spikes/big-data-mock/server.py --port 8200 --rows 100000`

## 2. 测试套件同步

snapshot 里**有**更新的测试，但磁盘上的 tests/ 是 T1.5 时期的旧版。从 snapshot 恢复：
- `tests/test_pagination.py` (T2.1 server-side pagination 测试)
- `tests/test_detail_cache.py` (get_object page-walking 测试)
- `tests/test_changelist_cache.py` (F4 反转：cache key **包含** p/per_page)

**结果**：114 passed, 0 failed, coverage 73.26% ≥ 70% ✓

## 3. 🎯 Filter 修复 — BigPost-100k bug

### 根因

`src/django_api_factory/admin.py` 的 `handle_search_condition` 单值用 `'in'`（子串）不是 `==`（相等）：

```python
# OLD
if len(search_terms) == 1 and sep not in search_terms[0]:
    return search_terms[0] in item_value  # '1' in '10' = True ❌
```

### 现象（100k BigPost 实测）

| URL | 之前 | 现在 |
|---|---|---|
| `?userId=1&p=1` | 14 行（userId `1, 10-19, 21, 31, 41`） | **1 行**（id=1, userId=1）✓ |
| `?userId=1&p=2` | 6 行（`51, 61, 71, 81, 91, 100`） | **0 行** ✓ |
| `?userId=99` | 0 行（substring 排除 99） | **0 行** ✓ |

### 修法

1. **抽出 `_handle_search_condition` 到 module-level**（`admin.py:43-92`）— 可直接 unit test，签名 `(item_value, search_terms, sep)`
2. **单值分支**：`int(s) == int(term)`（两边都尝试 int，相等返 True），失败 fallback `s == term`（字符串相等）。**不再用 `in`**
3. **多值分支**：OR-equals across terms，每个 term 也走 int-coerced 比较

### 测试

`tests/test_mixins.py` 末尾 5 个新 test，覆盖：
- 数字单值（userId=1 不误伤 userId=10/11/.../19/21/31）
- 字符串单值（title=foo 不误伤 foo/bar）
- int vs string normalization（API 返 int / URL 传 str 互转）
- 多值 OR-equals（userId=12 不命中 `?userId=1,2`）
- 多值 cell 用 separator 规范化

**结果**：119 passed, 0 failed, coverage 71.55% ≥ 70% ✓

## 4. 未修：paginator 总数

`_APIPaginator.count` 仍用 `expected_total`（= 100k）没用 filter 后的真长度。filter `?userId=1` 还是显示 2000 页（实际 1 页）。

**次要问题**，本次没动。`len(object_list)`（当前页的 filter 后行数）会更准，但会破坏"跳到第 1999 页"的能力。需要 API 支持 `X-Total-Count` 或显式声明 `expected_filtered_total` 才能彻底修。

## 5. 测试结果

```
======================== 119 passed, 3 warnings in 11.13s =========================
Required test coverage of 70% reached. Total coverage: 71.55%
```

## 6. 端到端验证（dev server 8141）

- 登录 admin/admin ✓
- `/admin/api/post/?userId=1` → 1 行（id=1）✓
- `/admin/api/post/?userId=1&p=2` → 0 行 ✓
- `/admin/api/bigpost/?p=1` → 50 行 ids 1-50 ✓
- `/admin/api/bigpost/?userId=1&p=1` → 1 行（id=1, userId=1）✓

Server 8141 仍开着（user 要测，这次不关）。
Mock server 8200 也仍开着（100k rows）。
