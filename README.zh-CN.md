# django-api-factory

[![CI](https://github.com/PianistSnk/django-api-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/PianistSnk/django-api-factory/actions)
[![Coverage](https://img.shields.io/badge/coverage-85.95%25-brightgreen.svg)](#testing)
[![Release](https://img.shields.io/badge/release-v0.1.2-blue.svg)](#install)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | [中文](README.zh-CN.md)

**把只读 REST API 数据显示到 Django admin 里 — 不写前端,也不为 API 行数据建数据库表。**

简单 API 只需要写 `url`; 如果上游 API 有自己的分页、筛选、排序参数,再 override `urls()`。

![REST API 行数据渲染为只读 Django admin changelist](https://raw.githubusercontent.com/PianistSnk/django-api-factory/master/docs/assets/api-to-admin.svg)

📖 **教程** — [1. Hello, APIModel (15 分钟)](docs/tutorials/01-hello-apimodel.md) · [2. 筛选/搜索/排序 (20 分钟)](docs/tutorials/02-filter-search-sort.md) · [3. 缓存/导出/自定义 action (25 分钟)](docs/tutorials/03-cache-export-actions.md)

## 为什么

Django admin 本来就是很实用的内部数据 UI。`django-api-factory` 让你把外部 REST 端点挂成 Django admin changelist,并保留动态列、分页、筛选、搜索、排序、导出和 Django view 权限。

## 30 秒上手

```python
# models.py
from django_api_factory.models import APIModel

class Post(APIModel):
    url = "https://jsonplaceholder.typicode.com/posts"

    class Meta(APIModel.Meta):
        verbose_name = "Post"
        verbose_name_plural = "Posts"

# admin.py
from django.contrib import admin
from django_api_factory.admin import APIAdmin

@admin.register(Post)
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
```

跑 `python manage.py runserver`,登录,打开这个模型的 Django admin changelist。

## 安装

```bash
pip install django-api-factory
```

## 跑示例

`examples/` 下有两个独立项目。选一个:

```bash
# 选 A:JSONPlaceholder(公共 REST API),从仓库根目录运行
pip install -e .
pip install -r examples/jsonplaceholder/requirements.txt
cd examples/jsonplaceholder
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

local-mock 的 100k 行示例需要两个终端:一个跑 mock API,一个跑 Django。

```bash
# 终端 1,从仓库根目录运行
pip install -e .
pip install -r examples/local-mock/requirements.txt
python examples/local-mock/mock_server.py --port 8200 --rows 100000
```

```bash
# 终端 2,从仓库根目录运行,使用同一个 virtualenv
cd examples/local-mock
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

浏览器打开 `http://127.0.0.1:8000/admin/` 看效果。

## 自定义钩子

多数项目可以从 `url` + `APIAdmin` 开始。下面这些钩子用于处理上游 API 或宿主项目的特殊需求。

### 1. 列和字段顺序

用 Django 原生 `list_display` 控制要显示的 API 字段和顺序。不设置时会自动显示 API 字段,但会排除 `api_exclude_fields`。
默认 `api_exclude_fields = ["id"]`,因为 `__str__` 已经作为详情链接显示这一行。

```python
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
```

如果用自动列,在 admin 类上排除噪音字段:

```python
class UserAdmin(APIAdmin):
    api_exclude_fields = ["id", "password", "ssn", "image"]
```

### 2. 多值字段分隔符

API 返回的字段如果用特定分隔符拼多值,可以改 `multi_value_separator`。默认分隔符是 `\u3001`。

```python
class PostAdmin(APIAdmin):
    multi_value_separator = ","
```

### 3. 查询 / 下载审计日志

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

### 4. 模态表单 action(`ActionFormMixin`)

```python
from django.contrib import admin
from django_api_factory.admin import APIAdmin

class PostAdmin(APIAdmin):
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

### 5. 可插拔缓存后端(无需 redis,默认无)

```python
from django_api_factory.mixins import RedisCacheBackend

class PostAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend  # 显式启用
    changelist_cache_enabled = True          # 5 分钟重复点击命中缓存
    changelist_cache_ttl = 300
```

不传 `cache_backend_class` 时,默认 `NullCacheBackend`(纯空操作,零依赖)。

### 6. Schema 注册(线程安全)

APIAdmin 第一次拿到数据时会自动调用 `schema_registry.register(model, fields)` 把 API 字段加到 model 上,你不需要手动调。

### 7. 短期 changelist 缓存(5 分钟重复点击,可选)

```python
class PostAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True  # 关闭 = 永远拉新数据
    changelist_cache_ttl = 300
```

默认 **关闭**(`changelist_cache_enabled = False`),库不会按 Django settings 自动选后端。

### 8. API 响应格式(envelope 拆包)

很多简单 REST 列表接口会直接返回裸数组:

```http
GET /api/orders         → 200 [{...}, {...}, ...]   ← 最简单的形态
GET /api/orders?page=2  → 200 [{...}, ...]          ← 分页走 query 参数
```

为兼容性,`APIModel.parse_response` 也支持常见 envelope 格式(按优先级,首个匹配胜出):

| 响应体 | 来源 |
|---|---|
| `[{...}]` | JSONPlaceholder 这类裸数组接口 |
| `{"data": [...]}` | Laravel 风格 / 自定义 API |
| `{"items": [...]}` | 常见自定义 API |
| `{"results": [...]}` | Django REST Framework `PageNumberPagination` 默认 |
| `{"rows": [...]}` / `{"records": [...]}` | 表格型 API |
| `{"users": [...], "total": 208}` | 只有一个顶层 list 字段的响应 |

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

嵌套 dict 默认会被拍平,比如 `{"company": {"name": "Acme"}}` 会变成 admin 里的 `companyName`。如果你能控制 API,直接返回裸数组仍然是最简单的方式。

## 测试

```bash
# 装 dev 依赖
pip install -e ".[dev]"

# 跑全量 + 覆盖率
pytest

# 跑单个文件
pytest tests/test_filter.py

# 看 HTML 覆盖率报告
open htmlcov/index.html
```

当前测试套件有 **246 个测试**,覆盖权限、筛选、分页、排序、响应解析、缓存钩子、弹窗 action 和项目级用法。当前覆盖率是 **85.90%**,并在 `pyproject.toml` 中用 `--cov-fail-under=70` 强制兜底。

## 权限

`APIModel` 子类默认只保留 `view` 权限,没有 `add`/`change`/`delete`。数据在别人 API 里,这个库只负责查看,不负责误编辑。

授权方式就是标准 Django auth:

1. 用 superuser 登录 `/admin/`。
2. 进入 **Users** 或 **Groups**,选择用户或组。
3. 在 **Permissions** 中勾选 `Can view <your_api_model>`。
4. 保存。

实现上,Django 5.2 会固定生成 `add/change/delete/view` 四个权限。库在 `apps.DjangoApiFactoryConfig.ready()` 里通过 `post_migrate` signal 删除前三个;重复运行 `manage.py migrate` 是幂等的。

你仍然需要正常跑 Django 的 `manage.py migrate` 来创建 `auth`、`admin`、permission 等表; `APIModel` 子类不会为 API 行数据创建业务表。

## License

MIT
