# django-api-factory

[![CI](https://github.com/PianistSnk/django-api-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/PianistSnk/django-api-factory/actions)
[![Coverage](https://img.shields.io/badge/coverage-80.19%25-brightgreen.svg)](#testing)
[![PyPI](https://img.shields.io/badge/pypi-v0.1.0--dev0-orange.svg)](#install)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | [中文](README.zh-CN.md)

**把任何 REST API 当作 Django admin 模型来管理 — 无需前端,无需数据库迁移,只需实现 `urls()` 和 `cache()`。**

3 年生产代码浓缩成 200 行包。

📖 **教程** — [1. Hello, APIModel (15 分钟)](docs/tutorials/01-hello-apimodel.md) · [2. 筛选/搜索/排序 (20 分钟)](docs/tutorials/02-filter-search-sort.md) · [3. 缓存/导出/自定义 action (25 分钟)](docs/tutorials/03-cache-export-actions.md)

## 为什么

Django admin 是世界上最快的 CRUD UI。数据在别人的 API 里,为什么要单独写一个前端?`django-api-factory` 让你把任何 REST 端点挂到 Django admin changelist 上 — 搜索、筛选、排序、导出全都白送。

## 30 秒上手

```python
# models.py
from django_api_factory.models import APIModel

class Post(APIModel):
    def urls(self, **kwargs):
        return "https://jsonplaceholder.typicode.com/posts"

    def cache(self, **kwargs):
        return None  # 关闭 Redis 缓存

# admin.py
from django_api_factory.admin import APIAdmin

@admin.register(Post)
class PostAdmin(APIAdmin):
    pass
```

跑 `python manage.py runserver`,登录,访问 `/admin/api/post/`,看到 API 数据。

## 安装

```bash
pip install django-api-factory
```

## 跑示例

`examples/` 下有两个独立项目。选一个:

```bash
# 选 A:jsonplaceholder(公共 REST API,总 ~40 行)
cd examples/jsonplaceholder
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver

# 选 B:local-mock(100k 行 + 4 种 envelope,需先起 mock server)
cd ../..   # 回仓库根
pip install -e .
python spikes/big-data-mock/server.py --port 8200 --rows 100000 &
cd examples/local-mock
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

或要看**一个项目里 5 个 admin 全跑**(传统 `example/`,仓库根),看 `example/README.md`。

浏览器打开 `http://127.0.0.1:8000/admin/` 看效果。

## 自定义钩子

### 1. 多值字段分隔符

API 返回的字段如果用特定分隔符拼多值(默认中文顿号 `、`),改 `api_field_separator`:

```python
class PostAdmin(APIAdmin):
    api_field_separator = ","
```

### 2. 查询 / 下载审计日志

```python
from django_api_factory.mixins import AuditLogMixin

class PostAdmin(AuditLogMixin, APIAdmin):
    enable_audit_log = True

    def log_query(self, request, model_name):
        from django.contrib.admin.models import LogEntry
        LogEntry.objects.create(
            action_flag=4,
            user=request.user,
            content_type=ContentType.objects.get(model=model_name),
        )
```

### 3. 模态表单 action(`ActionFormMixin`)

```python
from django_api_factory.mixins import ActionFormMixin

class PostAdmin(ActionFormMixin, APIAdmin):
    actions = ["add_remarks"]

    @admin.action(description="补充备注")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        return {"status": "success", "msg": f"Got remarks={remarks!r}"}

    add_remarks.layer = {
        "title": "补充备注",
        "params": [{"type": "input", "key": "remarks", "label": "备注说明"}],
    }
```

### 4. 可插拔缓存后端(无需 redis,默认无)

```python
from django_api_factory.mixins import RedisCacheBackend

class PostAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend  # 显式启用
    changelist_cache_enabled = True          # 5 分钟重复点击命中缓存
    changelist_cache_ttl = 300
```

不传 `cache_backend_class` 时,默认 `NullCacheBackend`(纯空操作,零依赖)。

### 5. Schema 注册(线程安全)

APIAdmin 第一次拿到数据时会自动调用 `schema_registry.register(model, fields)` 把 API 字段加到 model 上,你不需要手动调。

### 6. 短期 changelist 缓存(5 分钟重复点击,可选)

```python
class PostAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True  # 关闭 = 永远拉新数据
    changelist_cache_ttl = 300
```

默认 **关闭**(`changelist_cache_enabled = False`),库不会按 Django settings 自动选后端。

### 7. API 响应格式(envelope 拆包)

`django-api-factory` 遵循 [REST 约定](https://jsonapi.org/format/)([jsonplaceholder](https://jsonplaceholder.typicode.com/)、[GitHub](https://docs.github.com/en/rest)、[Stripe](https://stripe.com/docs/api)、[Google Cloud](https://cloud.google.com/apis/design) 都这么用):**列表端点直接返回裸数组**。

```http
GET /api/orders         → 200 [{...}, {...}, ...]   ← 推荐(REST 规范)
GET /api/orders?page=2  → 200 [{...}, ...]          ← 分页走 query 参数
```

为兼容性,`APIModel.parse_response` 也支持 3 种业界真实的 envelope 格式(按优先级,首个匹配胜出):

| 响应体 | 来源 |
|---|---|
| `[{...}]` | REST 规范(jsonplaceholder / GitHub / Stripe) |
| `{"data": [...]}` | 自家 API / Laravel 默认 |
| `{"items": [...]}` | 旧 internal API |
| `{"results": [...]}` | Django REST Framework `PageNumberPagination` 默认 |

**如果你的 API 用别的**,override `parse_response`:

```python
class LegacyOrder(APIModel):
    @classmethod
    def parse_response(cls, response_data):
        if isinstance(response_data, list):
            return response_data
        return response_data.get("payload", {}).get("rows", [])
```

默认不匹配时抛 `ValueError`,带清晰的提示告诉你怎么 override — 配错 envelope 时立刻看到,而不是静默渲染空 changelist。

我们**不发明第 5 种 key**(不造 `payload` / `rows` / `list` 这种非业界 key)。上面 4 种覆盖了主流 API 生态。如果你控制 API,**直接返裸数组**就完全不用这钩子。

## 状态

- [x] **v0.1.0-dev0** — M0: 浅克隆 demo,只读公共 API 可用
- [x] **M1 T1.1** — 剥离项目特定业务耦合(审计日志钩子 + 可配置多值分隔符 + `ActionFormMixin` 模态表单)
- [x] **M1 T1.2** — Redis 缓存后端可插拔(Null/Redis/自定义)
- [x] **M1 T1.3** — `SchemaRegistry` 一次性注册字段(idempotent,进程内线程安全)
- [x] **M1 T1.4** — `SchemaRegistry` 加 `threading.Lock`,防并发 `add_to_class` 竞态
- [x] **M1 T1.5** — `ActionFormMixin` 模态表单 + `changelist_cache_enabled` opt-in(默认关) + `detail_cache_enabled` opt-in(默认关)
- [x] **M1 T1.6** — 重写测试套件(88 tests,72% 覆盖,pytest-cov,HTML 报告,`--cov-fail-under=70`)
- [x] **M1 T1.6b** — `APIModel.parse_response` 钩子:4 种业界 envelope + override 路径(212 tests,80% 覆盖)
- [ ] M2: 服务端分页、流式、惰性
- [ ] M3: 文档、教程、示例
- [ ] M4: CI、PyPI 发布

## 测试

```bash
# 装 dev 依赖(带 pytest-cov)
pip install -e ".[dev]"

# 跑全量 + 覆盖率
pytest

# 跑单个文件
pytest tests/test_filter.py

# 看 HTML 覆盖率报告
open htmlcov/index.html
```

## 权限

`APIModel` 子类默认只有 `view` 权限,没有 `add`/`change`/`delete`(数据在别人 API 里,我们不让你误编辑)。通过 `apps.DjangoApiFactoryConfig.ready()` 的 `post_migrate` signal 自动剥离 `Meta.default_permissions`(Django 5.2 硬编码这 4 个权限,只能 post_migrate 删)。

## License

MIT
