# django-api-factory

[![CI](https://github.com/PianistSnk/django-api-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/PianistSnk/django-api-factory/actions)
[![Coverage](https://img.shields.io/badge/coverage-72.83%25-yellowgreen.svg)](#testing)
[![PyPI](https://img.shields.io/badge/pypi-v0.1.0--dev0-orange.svg)](#install)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Display any REST API as a Django admin model — no frontend, no migrations, just `urls()` and `cache()`.**

Three years of production-tested code distilled into a 200-line package.

## Why

Django admin is the fastest CRUD UI in existence. Why build a separate frontend for
data that lives in someone else's API? `django-api-factory` lets you mount any REST
endpoint as a Django admin changelist — search, filter, sort, export, all for free.

## 30-second example

```python
# models.py
from django_api_factory.models import APIModel

class Post(APIModel):
    def urls(self, **kwargs):
        return "https://jsonplaceholder.typicode.com/posts"

    def cache(self, **kwargs):
        return None  # disable Redis

# admin.py
from django_api_factory.admin import APIAdmin

@admin.register(Post)
class PostAdmin(APIAdmin):
    pass
```

Run `python manage.py runserver`, log in, visit `/admin/api/post/`, see your API data.

## Install

```bash
pip install django-api-factory
```

## Run the example

```bash
cd example
python -m venv .venv && source .venv/bin/activate
pip install "Django>=4.2" requests
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000/admin/api/post/ to see live data from JSONPlaceholder.

## Customization hooks

Two business-specific assumptions used to be hardcoded — both are now no-op by default and configurable per admin class.

### 1. Multi-value field separator

API responses may pack multiple values into one string with a separator. The default convention is the Chinese 顿号 `、`; your API may use `,`, `|`, `;`, etc.

```python
class PostAdmin(APIAdmin):
    multi_value_separator = ","  # default is "、"
```

### 2. Query / download audit log

The original code wrote to `django.contrib.admin.models.LogEntry` with custom `action_flag=4` (query) and `action_flag=6` (download). The library no longer writes any audit by default — subclass `AuditLogMixin` to add your own:

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

Note: as of M1, the library no longer ships a built-in `view_or_download` helper — implement the file proxy in your own project and call `self.log_download(...)` from there.

### 3. Modal-form actions (`ActionFormMixin`)

Add modal form + ajax submit to admin actions. The library auto-discovers any action function with a `.layer` attribute and shows a modal when the user clicks "Go" in the action dropdown.

```python
from django_api_factory.admin import APIAdmin  # already includes ActionFormMixin

class PostAdmin(APIAdmin):
    actions = ["add_remarks"]

    @admin.action(description="补充备注")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        status = request.POST.get("status", "")
        # ... do work
        return {"status": "success", "msg": f"Saved remarks={remarks!r}, status={status!r}"}

    # .layer schema is rendered as a modal; user's input lands in request.POST
    add_remarks.layer = {
        "title": "补充备注",
        "params": [
            {"type": "input", "key": "remarks", "label": "备注", "require": False},
            {"type": "radio", "key": "status", "label": "是否异常",
             "options": [{"key": "yes", "label": "是"}, {"key": "no", "label": "否"}]},
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
1. Skips already-registered fields (T1.3) — first request registers, all subsequent requests are O(1) lookups
2. Serializes registration with a `threading.Lock` (T1.4) — safe under multi-thread WSGI servers

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

## Status

- [x] **v0.1.0-dev0** — M0: shallow clone, works for read-only public APIs
- [x] **M1 T1.1** — strip project-specific business coupling (audit log hooks + configurable multi-value separator + `ActionFormMixin` modal-form)
- [x] **M1 T1.2** — Redis cache backend pluggable (Null/Redis/custom)
- [x] **M1 T1.3** — `SchemaRegistry` registers fields once (idempotent, intra-process thread-safe)
- [x] **M1 T1.4** — `threading.Lock` in SchemaRegistry prevents concurrent `add_to_class` races
- [x] **M1 T1.5** — `ActionFormMixin` modal-form + `changelist_cache_enabled` opt-in (default off) + `detail_cache_enabled` opt-in (default off)
- [x] **M1 T1.6** — rewrite test suite (88 tests, 72% coverage, pytest-cov, HTML report, `--cov-fail-under=70`)
- [ ] M2: server-side pagination, streaming, lazy
- [ ] M3: docs, tutorials, examples
- [ ] M4: CI, PyPI release

See `M1_T1.1_SCOPE.md` for the M1 breakdown.

## Testing

```bash
# Install dev dependencies (adds pytest-cov)
pip install -e ".[dev]"

# Run all tests + coverage report
pytest

# Run a single test file
pytest tests/test_filter.py -v

# View HTML coverage report
open htmlcov/index.html
```

The suite has **88 tests** covering the core (audit hooks, schema registry, action-form modal, detail/changelist cache, filter, app config). Coverage is **72%** with `--cov-fail-under=70` enforced in `pyproject.toml`. The remaining 28% is mostly inside `get_api_data` (the `requests.get` + data-munging path), which is better covered by end-to-end tests in the `example/` project than by unit tests.

## Permissions

`django-api-factory` is read-only: the data lives in someone else's REST
endpoint, not in your database, so users cannot add / change / delete
API-sourced rows. Only the `view_<modelname>` permission is auto-generated
per model.

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

## License

MIT
