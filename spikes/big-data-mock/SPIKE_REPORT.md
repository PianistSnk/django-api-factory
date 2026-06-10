# M2 A 档 Spike — 大数据集行为 (2026-06-08 16:11)

> **目的**: 装 1w / 10w / 100w 假数据，看当前 client-side 全量 cache 折中方案在什么规模下崩。
> **方法**: 启 mock REST server (10w 行 JSONPlaceholder 形态) + Django runserver 8141，curl 跑 6 档访问。
> **结论**: ≤ 1k 当前折中最优；10k 可用；100k 默认配置 1k 上限，**99% 数据看不见**。

---

## 工具

- **Mock server**: `spikes/big-data-mock/server.py` (4541 字节) — `http.server` + 内存 10w 行假 Posts（id 1-100000, userId 1-10000），支持 `?_page=N&_limit=M`，含 `X-Total-Count` header
- **BigPost model**: `example/api/models.py:BigPost` — urls() 指向 `http://127.0.0.1:8200/posts`
- **BigPostAdmin**: `example/api/admin.py:BigPostAdmin` — 简化配置（无 T1.6 filters / 无 actions / 测纯分页性能）

---

## 结果（6 档 × 5 操作）

| 规模 | `expected_total` | 首屏 | 翻页 | cache hit | 改 sort (重拉) | 改 per_page=200 |
|---|---|---|---|---|---|---|
| **1k** | 1k | 73ms / 531KB | 60ms | 60ms | 77ms | 75ms |
| **10k** | 10k | **1.01s / 4.99MB** | 0.98s | 0.98s | 1.15s | (n/a) |
| **100k** | 100k | **44.36s / 40.94MB** ❌ | (n/a) | (n/a) | (n/a) | (n/a) |
| **100k** | 1k (默认 1000 上限) | 65ms / 520KB | 60ms | (n/a) | (n/a) | (n/a) |

mock server 自身响应 1-3ms（10w 行 list 切片 O(page_size)），所以 admin 处理时间是真实数字。

---

## 关键发现

### 1. 10k 行 body 5MB 是什么？

之前以为 admin 渲染了 10k 行。**错** — 用 Python re 解析后发现：
- 1 个 `result_list` tbody，**50 个 `<tr>`**（per_page=50 的一页）
- per_page selector 5 个 options (10/25/50/100/200)
- pagination links 200 个 (10k / 50 = 200 页)

5MB body 主要是 200 个翻页链接 + 全部 `?p=1..200` 渲染的 query string + sidebar/header。**不是 10k 行数据**。

### 2. 100k 行配 expected_total=100k → **44 秒 / 40MB** ❌

`expected_total = 100_000` 触发 `get_api_urls(page=1&page_size=100000)` 一次性拉 100k 条。**100k × ~400 bytes = 40MB JSON**。44 秒里大部分是 mock server 序列化 + 网络 + admin 解析 + HTML 渲染。

`expected_total` 在 M2 折中里**不是"声明数据集大小"那么简单** — 它**直接控制 API 一次拉多少**。设得大 = 拉得多 = 慢 + 费内存。

### 3. 100k 行不配 expected_total → **99% 数据看不见** ⚠️

`expected_total` 不设时 `_get_cache_fetch_size()` fallback 到 `DEFAULT_CACHE_FETCH_SIZE = 1000`。API 拉 1k 条，admin 显示 "100 results"（其实是 1000 total，20 页）。**点 ?p=21 → HTTP 500**（paginator 越界 + get_results fallback 路径有 bug，未深查）。

这就是 T2.1 阻塞项"expected_total 必须显式声明"的**现场案例**：
- 业务接 100k 行 API → 不读 README 漏写 `expected_total` → 99% 数据不显示
- 想写 `expected_total=100k` → 首次加载 44s / 40MB 不可接受
- **没中间地带**

### 4. 翻页 / 改 per_page 不调 API（cache 命中）

所有 5 档"翻页"和"改 per_page"操作都在 60-80ms — **完全在 Django 渲染内**，**不调 mock server**。当前折中的"翻页不调网络"承诺属实。

### 5. 改 sort 触发 cache miss → 重拉全量

10k 行改 sort → 1.15s (重拉 10k + 重排 + 重渲染)。100k 行改 sort → 44s。

---

## 当前折中方案的真实适用区间

| 数据规模 | 用户体验 | 建议 |
|---|---|---|
| **≤ 1k 行** | ✅ 60-80ms 全程秒杀 | 当前折中最优 |
| **1k - 10k 行** | ⚠️ 1s 首屏 / 5MB body | 可用，UI 略卡 |
| **10k - 100k 行** | ❌ 1s+ 首屏 / 几 MB+ body | 需要 streaming 优化 |
| **≥ 100k 行** | ❌❌ 44s 首屏 / 40MB+ body | 必须 server-side 分页 + streaming |

---

## 给 M2 决策

1. **真做 T2.1 server-side 分页是必须的**（不是 nice-to-have）：
   - 10w 行真接进来当前必死
   - `expected_total=100k` 拉全量 44s 不能接受
   - 必须 API 接管 `?p=2&_limit=10` 返第 2 页 10 条
2. **T2.2 streaming 是 T2.1 的延伸**（不是独立任务）：
   - server-side 拉 1 页 = 省内存
   - streaming 拉 = 边拉边渲染（不用等整页 JSON 完整）
3. **T2.3 ETag/last-modified 在当前折中下几乎没用**：
   - 翻页不调 API
   - 只有改 filter / sort 调 API — 加 ETag 可省一次 304 round-trip
   - **价值小**（filter 改一次才会触发）

---

## Spike 产物

- `spikes/big-data-mock/server.py` (4541 字节) — 留作未来复现/扩展
- `example/api/models.py:BigPost` — 注册到 admin，方便手动浏览
- `example/api/admin.py:BigPostAdmin` — 简化版，可调整 `expected_total` 复跑

可重跑命令：
```bash
# 启 mock
venv/bin/python spikes/big-data-mock/server.py --port 8200 --rows 100000 &
# 启 Django
venv/bin/python example/manage.py runserver 127.0.0.1:8141 --noreload
# 然后浏览器开 http://127.0.0.1:8141/admin/api/bigpost/ (admin/admin)
```

---

## 1 个未深查的 bug（记下，不修）

`?p=21` 在 100k 数据 + 1k cache 时返 **HTTP 500**。预期：get_results 的 `except Exception: result_list = queryset._clone()` 应该 fallback。但实际 500。

可能原因：paginator.page(21) 抛的 EmptyPage 没被 `except Exception` 捕到（不应，可能 Django 有别的方式触发 500）— **没深查**。这是 user 接 100k 行时**会撞**的 bug，M1 / M2 修复时一起处理。
