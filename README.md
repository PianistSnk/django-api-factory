# django-api-factory

[![CI](https://github.com/PianistSnk/django-api-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/PianistSnk/django-api-factory/actions)
[![Coverage](https://img.shields.io/badge/coverage-85.90%25-brightgreen.svg)](#testing)
[![Release](https://img.shields.io/badge/release-v0.1.0-blue.svg)](#install)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md) | [中文](README.zh-CN.md)

**Display read-only REST API data in Django admin — no frontend and no database table for API rows.**

Use a fixed `url` for simple APIs, or override `urls()` when the upstream API
needs custom pagination, filtering, or sorting parameters.

📖 **Tutorials** — [1. Hello, APIModel (15 min)](docs/tutorials/01-hello-apimodel.md) · [2. Filter, search, sort (20 min)](docs/tutorials/02-filter-search-sort.md) · [3. Cache, export, custom actions (25 min)](docs/tutorials/03-cache-export-actions.md)

## Why

Django admin is already a useful internal data UI. `django-api-factory`
lets you mount external REST endpoints as Django admin changelists, with
dynamic columns, pagination, filters, search, sorting, exports, and Django
view permissions.

## 30-second example

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
    pass
```

Run `python manage.py runserver`, log in, and open the model's Django admin
changelist.

## Install

```bash
pip install django-api-factory
```

## Run the examples

Two standalone projects live under `examples/`. Pick one:

```bash
# Option A: JSONPlaceholder (public REST API), from the repo root
pip install -e .
pip install -r examples/jsonplaceholder/requirements.txt
cd examples/jsonplaceholder
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

For the local 100k-row example, run the mock API and Django app in two terminals:

```bash
# Terminal 1, from the repo root
pip install -e .
pip install -r examples/local-mock/requirements.txt
python examples/local-mock/mock_server.py --port 8200 --rows 100000
```

```bash
# Terminal 2, from the repo root, using the same virtualenv
cd examples/local-mock
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/`, log in, and choose the example model.

## Customization hooks

Most projects can start with `url` plus `APIAdmin`. Use these hooks when the
upstream API or the host project needs more control.

### 1. Multi-value field separator

API responses may pack multiple values into one string with a separator. The
default is the ideographic comma (`\u3001`); your API may use `,`, `|`, `;`,
or another separator.

```python
class PostAdmin(APIAdmin):
    multi_value_separator = ","  # default is "\u3001"
```

### 2. Query / download audit log

Some projects write to `django.contrib.admin.models.LogEntry` with custom `action_flag=4` (query) and `action_flag=6` (download). The library does not write any audit by default — subclass `AuditLogMixin` to add your own:

```python
from django_api_factory.admin import APIAdmin
from django_api_factory.mixins import AuditLogMixin
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
import datetime


class MyAuditedAdmin(AuditLogMixin, APIAdmin):
    def log_query(self, request, model_name):
        LogEntry.objects.create(
            action_time=datetime.datetime.now(),
            user=request.user,
            action_flag=4,  # your custom flag
            content_type=ContentType.objects.get(model=model_name),
        )

    def log_download(self, request, model_name, filename, type_):
        LogEntry.objects.create(
            action_time=datetime.datetime.now(),
            user=request.user,
            action_flag=6,
            object_repr=f"{filename}.{type_}",
            content_type=ContentType.objects.get(model=model_name),
        )
```

Note: the library does not ship a built-in `view_or_download` helper — implement the file proxy in your own project and call `self.log_download(...)` from there.

### 3. Modal-form actions (`ActionFormMixin`)

Add modal form + ajax submit to admin actions. The library auto-discovers any action function with a `.layer` attribute and shows a modal when the user clicks "Go" in the action dropdown.

```python
from django.contrib import admin
from django_api_factory.admin import APIAdmin  # already includes ActionFormMixin

class PostAdmin(APIAdmin):
    actions = ["add_remarks"]

    @admin.action(description="Add remarks")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        status = request.POST.get("status", "")
        # ... do work
        return {"status": "success", "msg": f"Saved remarks={remarks!r}, status={status!r}"}

    # .layer schema is rendered as a modal; user's input lands in request.POST
    add_remarks.layer = {
        "title": "Add remarks",
        "params": [
            {"type": "input", "key": "remarks", "label": "Remarks", "require": False},
            {"type": "radio", "key": "status", "label": "Is anomaly?",
             "options": [{"key": "yes", "label": "Yes"}, {"key": "no", "label": "No"}]},
        ],
    }
```

Supported `params` types: `input` (text/number/date/etc.), `textarea`, `select`, `radio`, `file`.

### 4. Pluggable cache backend (no redis required, opt-in)

The core library does not import redis-py at module load. The default cache backend is `NullCacheBackend` (no-op), so the library works out-of-the-box without any cache configuration or coupling.

**Default = no caching, anywhere.** Both `detail_cache_enabled` and `changelist_cache_enabled` default to `False`. To use Redis or any other backend, opt in explicitly:

```python
from django_api_factory.admin import APIAdmin
from django_api_factory.mixins import RedisCacheBackend, NullCacheBackend


class CachedAdmin(APIAdmin):
    # Opt in to a backend
    cache_backend_class = RedisCacheBackend  # reads REDIS_HOST/PORT/DB/PWD
    # Opt in to detail-view caching
    detail_cache_enabled = True
    detail_cache_ttl = 600  # 10 min
    # Opt in to short-term changelist caching (5 min by default)
    changelist_cache_enabled = True
    changelist_cache_ttl = 300


class NoCacheAdmin(APIAdmin):
    cache_backend_class = NullCacheBackend  # explicit no-op (default behavior)
```

To plug in your own backend (memcached, Django cache, etc.), subclass `BaseCacheBackend`:

```python
from django_api_factory.mixins import BaseCacheBackend


class DjangoCacheBackend(BaseCacheBackend):
    def get(self, key):
        from django.core.cache import cache
        return cache.get(key)

    def set(self, key, value, ttl):
        from django.core.cache import cache
        cache.set(key, value, ttl)

    def delete(self, key):
        from django.core.cache import cache
        cache.delete(key)
```

### 5. Schema registry — register fields once (thread-safe)

The `get_api_data` flow adds API-returned fields to the model class via `add_to_class(...)` so Django admin can render them. Without a registry, this `O(N)` loop runs on every request and is vulnerable to multi-thread races.

`django-api-factory` provides a module-level `schema_registry` (singleton) that:
1. Skips already-registered fields — first request registers, all subsequent requests are O(1) lookups
2. Serializes registration with a `threading.Lock` — safe under multi-thread WSGI servers

```python
from django_api_factory.mixins import schema_registry

# Automatic: APIAdmin.get_api_data() calls schema_registry.register(model, fields)
# You don't need to call this manually in normal use.

# Advanced: inspect / reset
schema_registry.is_registered(MyModel, "field_name")  # bool
schema_registry.registered_fields(MyModel)            # list[str]
schema_registry.reset()  # in tests
```

If you build fields manually (e.g. a custom `get_api_data` subclass), call `register` yourself to keep the registry in sync:

```python
class MyAdmin(APIAdmin):
    def get_api_data(self, request):
        data = self._fetch_from_api(request)
        fields = list(data[0].keys()) if data else ["id"]
        from django_api_factory.mixins import schema_registry
        schema_registry.register(self.model, fields)
        # ... rest of the method
```

For multi-process setups (gunicorn workers), each worker process builds its own registry — the lock is intra-process only. This is fine because Django's model class registry is also per-process.

### 6. Short-term changelist cache (5-min repeat clicks, opt-in)

When a user clicks a changelist twice within 5 minutes, the second click usually returns the same data the API was returning seconds ago. To avoid that second API call, enable the short-term changelist cache:

```python
class MyAdmin(APIAdmin):
    cache_backend_class = RedisCacheBackend  # or any BaseCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300  # 5 min
```

How it works:
- `get_api_data` checks the cache BEFORE calling the API. On hit, it skips the network call entirely.
- The cache key includes user, model, and the full GET params (including `p` and `o`), so different users / pages / sorts don't stomp on each other.
- TTL is short by default (5 min) so the user always sees reasonably fresh data.

This is **opt-in** — by default `changelist_cache_enabled = False`. The library does not pick a backend based on Django settings.

### 7. API response format (envelope unwrap)

Many simple REST list endpoints return a bare array:

```http
GET /api/orders         → 200 [{...}, {...}, ...]   ← simplest shape
GET /api/orders?page=2  → 200 [{...}, ...]          ← pagination via query params
```

For compatibility, `APIModel.parse_response` also handles common envelope
shapes that appear in real APIs (in priority order, first match wins):

| Response body                          | Source                                                |
| -------------------------------------- | ----------------------------------------------------- |
| `[{...}]`                              | Bare list endpoints such as JSONPlaceholder          |
| `{"data": [...]}`                      | Laravel-style and custom APIs                        |
| `{"items": [...]}`                     | Common custom APIs                                    |
| `{"results": [...]}`                   | Django REST Framework `PageNumberPagination` default  |
| `{"rows": [...]}` / `{"records": [...]}` | Table-style APIs                                   |
| `{"users": [...], "total": 208}`       | Any response with exactly one top-level list field    |

**If your API uses something else**, override `parse_response` on your
`APIModel` subclass:

```python
class LegacyOrder(APIModel):
    @classmethod
    def parse_response(cls, response_data):
        if isinstance(response_data, list):
            return response_data
        return response_data.get("payload", {}).get("rows", [])
```

The default raises `ValueError` with a clear message telling you how to
override — so a misconfigured envelope shows up immediately rather than
silently rendering an empty changelist.

Nested row dictionaries are flattened by default, so
`{"company": {"name": "Acme"}}` becomes `companyName` in the admin.
If you control the API, returning a bare array remains the simplest path.

See `docs/tutorials/` for step-by-step usage guides.

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests + coverage report
pytest

# Run a single test file
pytest tests/test_filter.py -v

# View HTML coverage report
open htmlcov/index.html
```

The suite has **246 tests** covering permissions, filters, pagination,
sorting, response parsing, cache hooks, modal actions, and project-level
usage. Coverage is currently **85.90%** with `--cov-fail-under=70`
enforced in `pyproject.toml`.

## Permissions

`django-api-factory` is read-only: the data lives in someone else's REST
endpoint, not in your database, so users cannot add / change / delete
API-sourced rows. Only the `view_<modelname>` permission is kept per model.

Granting access is just standard Django auth:

1. Log into `/admin/` as a superuser.
2. Go to **Users** or **Groups** → select the user / group.
3. Under **Permissions**, tick the `Can view <your_api_model>` row(s).
4. Save.

Now that staff user (non-superuser) can browse the changelist for the
selected API model, but cannot mutate anything.

Implementation: Django 5.2 ignores `Meta.default_permissions` and always
auto-generates `('add', 'change', 'delete', 'view')`. We trim the
unwanted three via a `post_migrate` signal handler in
`apps.DjangoApiFactoryConfig.ready()` — re-runs of `manage.py migrate`
are idempotent.

You still run Django's normal `manage.py migrate` for `auth`, `admin`, and
permission tables; `APIModel` subclasses do not create data tables for API
rows.

## License

MIT
