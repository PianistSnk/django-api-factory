# django-api-factory 项目讲解

> 给一个"听说过这个项目但没看代码"的人 15 分钟讲清楚。
> 写于 2026-06-09，master 分支 9 个 commit，140 单测 / 72.68% 覆盖率。

---

## TL;DR

**一句话**：把任意 REST API 在 Django admin 里渲染成"可管理的数据表"——搜索、过滤、排序、分页、详情页全免费。**不用写前端，不用建数据库表**。

**30 秒例子**：

```python
class Post(APIModel):
    def urls(self, **kwargs):
        return "https://jsonplaceholder.typicode.com/posts"

    def cache(self, **kwargs):
        return None

@admin.register(Post)
class PostAdmin(APIAdmin):
    pass
```

访问 `/admin/api/post/`，100 行 JSONPlaceholder 数据立刻渲染成 Django admin 的 changelist——分页、过滤、搜索、详情全有。

**核心价值不是"通用化框架"**——是"零摩擦 admin 工具"：一个 200 行的包，背后是 3-4 年在the team里"无前端快速开发"模式的沉淀。

---

## 1. 起源：3-4 年攒下的"零摩擦"经验

这个项目的源头在 2022 年左右，the team里有个内部仓库 `the original code/APIFactory`（admin.py 单文件 23K，名字是the teaminternal project name）。逻辑一句话：

> **写 SQL → 抄成 Model → 改 URL → admin 抄名字写个 `pass` → 重启 → 完事**

每个新接的外部 API（客户数据 / 风控接口 / 第三方平台）都走这个流程。原本这些数据要"前端起 React 项目 + 后端 ORM 包一层 + 联调 + 部署"，3 天起步。改走 admin 之后，**15 分钟**出一个能查能筛能导的内部工具。

3-4 年下来，攒了几十个 `xxxAdmin`，每个都是 `pass`。这就是"零摩擦"——业务没空没人改它，但只要改就能马上用。

**为什么 2026 年要拆出来？**

旧 `admin.py` 23K 写得糙，剥业务耦合成本高，没法发出去复用。**目标很朴素**：把"admin 增强"这层拆成可独立贡献的模块，让 `django-api-factory` 能脱开the team业务包、装到任何一个 Django 项目里就跑。**不是要做成"通用化大框架"**——那是另一种死法。

---

## 2. 核心架构：4 个文件 + 3 个抽象

整个包是 6 个文件，其中**有内容的是 4 个**：

| 文件 | 行数 | 职责 |
|---|---|---|
| `admin.py` | 23K | `APIAdmin`：主战场，混了一堆 mixin |
| `models.py` | 0.5K | `APIModel` 抽象基类 |
| `filter.py` | 1.3K | `APIFilter` / `APIMultiSelectFilter` |
| `changelist.py` | 0.1K | `APIChangeList`（覆写 get_filters_params 剥 per_page） |
| `queryset.py` | 0.3K | `MyQuerySet`（浅拷贝链式） |
| `mixins.py` | — | `BaseCacheBackend` / `AuditLogMixin` / `SchemaRegistry` |

**3 个抽象**：

### 2.1 `APIModel` — 抽象基类，强制 `urls()` / `cache()`

```python
class APIModel(models.Model):
    class Meta:
        abstract = True
        managed = False
        default_permissions = []
    def urls(self, **kwargs): raise NotImplementedError
    def cache(self, **kwargs): raise NotImplementedError
```

- `managed = False` → Django 不会要求你 migrate
- `default_permissions = []` → 不要 add/change/delete 权限（Django admin 默认行为）
- 强制子类实现 `urls()` 和 `cache()` → 业务关键决策（数据来源 + 缓存策略）**不能逃课**

### 2.2 `APIAdmin` — 重写 `get_api_data(request)`，自己当 datasource

`get_api_data` 是整个包的心脏：拿 HTTP request，组装 URL，发请求，解析 JSON，**根据响应字段动态 `model.add_to_class(field_name, field_def)`**，最后返回 list of dict。

`add_to_class` 这步是为了让 Django admin 知道这个 model 有哪些字段可显示。**问题**：每次请求都跑一遍，O(N) 字段 × N 字段类型反射，**而且多线程下互相覆盖**。M1 T1.3/T1.4 解决了这个：模块级 `SchemaRegistry` 单例 + `threading.Lock`——首次注册后 O(1) 查表。

### 2.3 `MyQuerySet` + `APIChangeList` — 浅拷贝链式 + 剥 per_page

`MyQuerySet` 就 30 行，浅拷贝链式调用的 `_clone()`。`APIChangeList` 也很小，**只覆写一件事**：把 `?per_page=N` 从 `filters_params` 里剥掉（per_page 不属于"过滤条件"，要单独处理）。

剩下的"分页 / 排序 / 搜索"全交给 Django admin 自己的 `ChangeList`——**这是这套架构最讨巧的地方**。我们没重写 admin 任何东西，只是给 model 喂数据 + 改了一点点 ChangeList 行为。

---

## 3. 时间线：M0 → M1 → M2

### M0：浅克隆（1.5h，2026-06-05 凌晨）

把老 `admin.py` 拆出来到独立包，剥 the original code 业务耦合（顿号搜索、LogEntry 审计、simpleui）。**3 个 smoke test + 2 个 e2e test 验证 `/admin/api/post/` 200**。第一次"独立包跑通"。

### M1：剥业务 + 修复 5 个历史坑（~30h，06-05 ~ 06-07）

| T | 状态 | 内容 |
|---|---|---|
| T1.1 | ✅ | 剥 LogEntry 审计 → `AuditLogMixin`（默认 no-op） |
| T1.2 | ✅ | 剥 simpleui / Redis → `NullCacheBackend` 默认 + `RedisCacheBackend` opt-in |
| T1.3 | ✅ | `SchemaRegistry` 注册一次（idempotent） |
| T1.4 | ✅ | `threading.Lock` 防 add_to_class 并发覆盖 |
| T1.5 | ✅ | 测试套件 88 个 + 72% 覆盖率（`pytest-cov` + `--cov-fail-under=70`） |
| T1.6 | ✅ | **Filter UX 重写**：单选/多选可混用 + 「确定/清空」+ 互斥 `<details>` + 本地搜索 |
| T1.6+ | ✅ | 接 CoinGecko 公共 API（1.4w 币） + 修 `detail int(id) bug` |

**T1.6 是一段小故事**——见下文"踩过的坑"。

### M2：大数据集 + Server-side 分页（~10h，06-08 ~ 06-09）

| T | 状态 | 内容 |
|---|---|---|
| M2 spike A | ✅ | 1w / 10w / 100w 行假数据测性能 |
| T2.1 MVP | ✅ | Server-side 分页（100k → 47ms/67KB，900x 提升） |
| T2.1 F1 | ✅ | 修 `?p=越界` 500（`page_num` clamp 到末页） |
| T2.1 F2/F4/F5 | ✅ | README 写 `expected_total` 红字警告 / changelist_cache 改按页 / 杂项清理 |
| Filter 系列 | ✅ | `?userId=1` 不再误伤 10-19 / dropdown cap 200 / 跨页 distinct / AJAX search + load more |
| 跨页 filter | ✅ | API 透传 filter kwargs + `X-Total-Count` header（paginator 用真实数） |
| per_page | ✅ | dropdown 放大到 2000/10000（大 dataset 压测） |

---

## 4. 关键技术决策

### 4.1 "不动 Django admin" 是核心

最关键的架构决策是**不重写 admin**。Django admin 已经有：
- Changelist 渲染（分页、排序、过滤槽、搜索栏）
- 详情页 / 编辑页 / 添加页
- 权限 / 登录 / CSRF / i18n
- 主题系统（simpleui）
- Admin actions（批量操作）
- 导出（admin_export 之类）

我们只做两件事：**给它喂 list-of-dict**（`get_api_data`），**给它补 model 字段**（`add_to_class` + `SchemaRegistry`）。**`APIAdmin(MyModelAdmin)`** 然后**子类只写 `pass`** 就能跑。

代价是：admin 改版（Django 4→5）我们要跟着改。但这是"用别人轮子"的代价，可以接受。

### 4.2 Cache backend 是 opt-in，默认 Null

```python
class CachedAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend  # opt in
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
```

**默认 `NullCacheBackend` = no-op**——没装 Redis 也能跑。**这跟早期"硬编码 Redis"的旧实现是反的**。理由：把"是否需要 cache"的选择权交给使用者，库本身不替你决定。

代价：第一次接 API 的人会问"我该不该开 cache？"——README 里给了一个判断标准（数据变化频率 + 调用频率）。但本质是 trade-off：

- **不开**：每次请求都打 API，简单
- **开**：5 分钟内重复点击省一次 API call，但 cache key 设计复杂（要含 user / model / 所有 GET params）

### 4.3 SchemaRegistry 解决"动态 model 字段"问题

API 响应字段是动态的，但 Django model 的字段是静态的。解法：

```python
# 第一次请求
fields = list(data[0].keys())  # ['id', 'title', 'body', 'userId']
schema_registry.register(Post, fields)
# 后续请求
schema_registry.registered_fields(Post)  # O(1) 查表
```

**`threading.Lock` 在 `register()` 里**——多线程 WSGI worker 同时打过来，不会互相覆盖 `add_to_class`。每个 worker 进程有自己的 registry（Django model class 也是 per-process 的，行为一致）。

### 4.4 `expected_total` 是分页的"用户责任"

Django admin 的 paginator 不知道 API 一共有多少行。我们要 `expected_total = 100_000` **显式声明**——这个数字告诉 paginator "2000 页"。

**不写** → 默认 1000 上限 → 99k 数据**看不见** + `?p=21` 越界 500。

**当前 trade-off**：
- `expected_total` 在 filter 之后**不会重新算**（"跳到第 1999 页"的能力保留，但 filter 后总数不准）
- 彻底修法：API 返 `X-Total-Count` header（已支持，Post + BigPost 都 work）

---

## 5. 踩过的坑（教训清单）

### 5.1 `{# #}` 是 Django 模板的**单行注释**——多行原样输出到 HTML

第 **6 次**踩这个坑（SOUL.md hard rule）。某次提交 3 段 `{# ... #}` 多行注释**没报错没警告**地原样输出到 filter dropdown 的每个 `<li>` 里，用户截图才发现。

**修法**：永远不写 `{# `——包括单行也别写。用 `{% comment %}` 替代（多行 OK、不会渲染）。要写注释冲动时，**先停 3 秒**问"我能不能在 commit message 里写"。

### 5.2 Django 4.x admin `change_list.html` **没有** `{% block extrascript %}`

T1.6.0 ~ T1.6.2 期间，**3 次写 JS** 都被静默丢掉，**7 小时不知道**。每次我以为"代码写错了"，反复重写 3 次方向。**根因是 block 错**。

**修法**：改任何 block 之前先 `grep "block " <父模板路径>` 看实际支持哪些。Debug "JS 不 work" 第一件事：`curl + grep` 关键 JS 函数名，0 = block 错 / JS 没注入。

### 5.3 Django 5+ `QueryDict.items()` 返 `(key, [value])` 列表

T2.1 改了 `dict(request.GET.items())`——`?p=2` 变成 `{'p': ['2']}`，`int(['2'])` 抛 `ValueError`，兜底 `page=1`，**所有 `?p=N` 都返 page 1 数据**。

**修法**：起点把 list value 拍平：`{k: v[0] if isinstance(v, list) else v for k, v in request.GET.items()}`。**测试要覆盖**：用 `RequestFactory` 造真实 request 验证。

### 5.4 Django 模板禁止 `_` 开头属性

`{{ spec._total_count }}` 抛 `TemplateSyntaxError: Variables and attributes may not begin with underscores`。**Python 端同时存 `_total_count`（兼容老代码）+ `total_count`（模板用）**。

### 5.5 真实生产 bug：`?userId=1` 把 14 行圈进来

`handle_search_condition` 单值用 `'in'`（子串）不是 `==`：

```python
return search_terms[0] in item_value  # '1' in '10' = True ❌
```

`?userId=1&p=1` 在 100k BigPost 返 **14 行**（userId `1, 10-19, 21, 31, 41`）。**用户实测发现**——只盯着"返回行数对不对"是抓不到的，要看 `id` 列表。

**修法**：`int(s) == int(term)`（两边都尝试 int，相等返 True），失败 fallback `s == term`（字符串相等）。

### 5.6 详情页 100-cap 锁住 page 2000 的 id

`get_object` 走 `1..min(max_pages, 100)` loop 找 id，但 100 cap 截住，id 99999（在 page 2000）**永远到不了**。

**修法**：fast path 1 次 API call 算 `target_page`，命中即返；不命中才走 100-cap slow path。**实测**：id 1, 50, 100, 5000, 10000, 50000, 75000, 99999, 100000 → 200 (~10ms)。

### 5.7 Snapshot 不要成为"事实唯一来源"

M0 → M2 一路都是 `tar.gz` 备份 + 没 commit。**M2 全部工作只在 snapshot 里**，git log 看不到。用户某天问"git 里有代码啊"——才发现 M2 没 commit 过。

**修法**：重要 milestone 必 commit；snapshot 是 belt-and-suspenders 不是替代。

---

## 6. M2 大数据集优化战

### 6.1 Spike A：10w 行"性能"不是问题

跑了 3 个方案（pure-python / pandas / SQLite）做对比，**所有方案 4 个 query 都在个位数 ms**。

**根因不是查询慢**——是 `add_to_class` 每次请求重建 + admin form rendering。

但**M1 之后 T2.1 走 server-side 分页**之后，**100k 行的体验**：

| 操作 | 旧 (T1.6) | 新 (T2.1) |
|---|---|---|
| 首屏 `?p=1` | **44s / 40MB** | **47ms / 67KB** |
| 翻页 | cache miss 1.5s | 60ms (cache) |
| 改 sort | 重拉全量 44s | 重拉全量 44s（cache miss） |

**900x 快、600x 小**——靠的是 "API 真的传 `?page=N&page_size=M`" + "paginator 真的去 API 拉当前页"。

### 6.2 跨页 filter 是另一道坎

T2.1 改 server-side 分页后，admin 拿每页 50 条**在内存里 filter**——100k 数据里 userId=1 的 10 条分散在 2000 页，老代码只能看到当前页的 userId=1。

**修法**：
1. Mock server 加 server-side filter（`?userId=N&title=...`）+ 返 `X-Total-Count` header
2. `Post.urls()` 透传 `**kwargs` 到 query string（`urllib.parse.quote` 编码）
3. Admin 读 `X-Total-Count` → `self._api_filtered_total`
4. `get_paginator` 优先级：`_api_filtered_total` → `expected_total` → 0

**验证**：

| URL | 之前 | 现在 |
|---|---|---|
| `?userId=1&p=1` | 1 行 | **10 行** (ids 1, 10001, 20001, ..., 90001) |
| Paginator | 2000 页 | **1 页** (X-Total-Count=10) |

### 6.3 当前已知 trade-off

1. **Filter 总数 vs 跳页能力**：`expected_total` 不重算 → 翻页正确 / filter 后"总共 N 页"不准
2. **Cache key 设计**：按页 cache → 翻页友好；按 query cache → filter 友好——**只能选一个**
3. **GET params 列表化**：`X-Total-Count` header 不是所有 API 都返（要 client-side fallback）

---

## 7. 还在做的方向

| 主题 | 状态 | 思路 |
|---|---|---|
| Filter UX polish | ⏸️ | 搜索高亮、键盘导航、server-side sort |
| T2.2 streaming | ⏸️ | T2.1 延伸（省内存 + 边拉边渲染），10w+ 行必备 |
| T2.3 ETag | ⏸️ | 改 filter/sort 调 API 时省一次往返——价值小，留着 |
| 模块化贡献 | 🎯 | 把 admin 增强拆成可独立贡献的包（不只 core） |
| M3 docs | ⏸️ | 教程、例子、API reference |
| M4 PyPI | ⏸️ | `pip install django-api-factory` + CI |

**核心原则不变**：**核心价值是"零摩擦 admin 工具"，不是通用化框架**。每加一个 feature 先问——**"这个 feature 让我下次 15 分钟出一个新 admin 吗？"** 不能的话不做。

---

## 8. 怎么用

- **给同事看**：直接发这个文件，10 分钟读完
- **改改发博客**：结构已经分章节，截 8 个里程碑段落
- **自己归档**：放项目根，跟 `M0_DONE.md` / `M1_T1.6_DONE.md` 一脉相承
- **配 demo 录屏**：demo 起来后补一个 5 分钟录屏（按方案 C）

---

## 9. 数字总览（2026-06-09 23:40）

| 指标 | 数字 |
|---|---|
| 包大小 | 6 个 Python 文件 + 2 个 Django 模板 |
| 核心代码 | admin.py 23K / 其他 4 个文件共 ~2.3K |
| 测试 | 140 passed / 0 failed |
| 覆盖率 | 72.68% (≥ 70% fail-under 强制) |
| Git commit | 9 个（M0 → M2 跨页 filter → filter AJAX） |
| 文档 milestone | 7 份 `M*_DONE.md` + 1 份 README + 4 份 spike 报告 |
| 公开 API 实测 | Post (100 行) / BigPost (100k 行 mock) / CoinGecko (1.4w 币) |

---

_写完时间：2026-06-09 23:40 CST_
_写的人：MiniMax-M3 (per-session assistant)_
_主笔：用户（用 9 个 commit + 7 份 milestone 文档喂给我的）_
