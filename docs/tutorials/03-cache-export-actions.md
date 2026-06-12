# Tutorial 3: Cache, export, custom actions

> Time: 25 minutes
> Prerequisite: completed [Tutorial 2](02-filter-search-sort.md).
> Goal: Add Redis caching (optional), a bulk Excel export action, and a Modal-form action — the full "zero-friction internal tool" pattern.

---

## What you'll build

The same Post admin, but with:

- A 5-minute Redis cache (optional — falls back to no cache)
- A "Export to Excel" action that downloads all 100 posts as a workbook
- A "Mark as published" Modal-form action that asks for a date then
  reports the count
- An "audit log" hook that records every changelist load to
  `django_admin_log`

![actions screenshot](https://placehold.co/600x300?text=Actions+screenshot+here)

---

## 1. Optional: Redis cache (5 min)

> **Skip this section if you don't have Redis** — the default
> `NullCacheBackend` is a no-op and the rest of the tutorial works
> identically. We deliberately do **not** auto-pick a backend based
> on `settings.py` — caching is opt-in.

```bash
# macOS:
brew install redis && brew services start redis
# Linux (Debian/Ubuntu):
sudo apt install redis-server && sudo systemctl start redis
```

Add to `requirements.txt`:

```
redis>=5.0
```

(Already a dev dependency of `django-api-factory[dev]`.)

Edit `blog/admin.py`:

```python
from django_api_factory.mixins import RedisCacheBackend


@admin.register(Post)
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]

    # Opt in to Redis caching:
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True   # 5-min repeat-click cache
    changelist_cache_ttl = 300        # seconds
    detail_cache_enabled = True       # 5-min detail page cache
    detail_cache_ttl = 300
```

Reload the admin twice in 5 minutes. The first request takes ~300ms
(cross-Pacific JSONPlaceholder), the second takes ~30ms (cache hit).

> **Why opt-in?** Auto-enabling Redis in a project that doesn't
> expect it leads to "wait, why is my admin so fast all of a sudden?"
> and "wait, why is my data 5 minutes stale?" debugging. Opt-in is
> intentional.

---

## 2. Bulk Excel export action (10 min)

`django-api-factory` ships `ExportMixin` (in `django_api_factory.mixins`)
that adds `export_to_excel` to your admin's `actions` dropdown.

```bash
pip install openpyxl   # one-time, for the Excel writer
```

Edit `blog/admin.py`:

```python
from django_api_factory.mixins import ExportMixin, RedisCacheBackend


@admin.register(Post)
class PostAdmin(ExportMixin, APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
```

Go to `/admin/blog/post/`, select all 100 rows via the action checkbox,
pick "Export to Excel" from the actions dropdown, click "Go". You get
`posts.xlsx` with all selected rows.

> By default the export reads from the same `api_list` the changelist
> uses, so filter + sort + search all apply. For 100k rows, the export
> fetches `?per_page=100000` from the cache (or API if cache miss).

---

## 3. Custom Modal-form action (8 min)

`ActionFormMixin` lets you define an action that pops up a modal form
asking the user for inputs (e.g. a date, a comment) before the action
runs.

Edit `blog/admin.py`:

```python
from django.contrib import admin
from django_api_factory.mixins import ActionFormMixin, ExportMixin, RedisCacheBackend
from django_api_factory.filter import APIFilter, APIMultiSelectFilter

from .models import Post


@admin.register(Post)
class PostAdmin(ActionFormMixin, ExportMixin, APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
    actions = ["add_remarks"]

    @admin.action(description="补充备注")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        status = request.POST.get("status", "")
        return {
            "status": "success",
            "msg": (
                f"Got remarks={remarks!r}, status={status!r}, "
                f"selected {len(list(queryset))} row(s)."
            ),
        }

    # Modal form config — the action's UI.
    add_remarks.layer = {
        "title": "补充备注",
        "width": "480px",
        "params": [
            {"type": "input", "key": "remarks",
             "label": "备注说明", "require": True},
            {"type": "radio", "key": "status",
             "label": "是否异常",
             "options": [
                 {"key": "是", "label": "是"},
                 {"key": "否", "label": "否"},
             ]},
        ],
    }
```

Reload the admin. The actions dropdown now has "补充备注". Selecting
rows and clicking it pops up the modal. Fill in remarks + status,
submit, and you'll get a success message in the admin (or your
custom UI handling).

---

## 4. Optional: audit log (2 min)

If you want every changelist load and every download to leave a
`django_admin_log` row, mix in `AuditLogMixin`:

```python
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.contrib.contenttypes.models import ContentType
from django_api_factory.mixins import AuditLogMixin


@admin.register(Post)
class PostAdmin(AuditLogMixin, ActionFormMixin, ExportMixin, APIAdmin):
    enable_audit_log = True
    # ... other config ...

    def log_query(self, request, model_name):
        LogEntry.objects.create(
            action_flag=CHANGE,  # 2; or define your own flag
            user=request.user,
            change_message="changelist query",
            content_type=ContentType.objects.get(model=model_name),
        )
```

> `log_query` and `log_download` are no-ops by default — the mixin
> just gives you the hooks. Override them to write wherever you want.

---

## 5. Final admin (5 min)

Your `blog/admin.py` should now look like:

```python
from django.contrib import admin
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType

from django_api_factory.admin import APIAdmin
from django_api_factory.filter import APIFilter, APIMultiSelectFilter
from django_api_factory.mixins import (
    ActionFormMixin, AuditLogMixin, ExportMixin, RedisCacheBackend,
)

from .models import Post


@admin.register(Post)
class PostAdmin(
    AuditLogMixin,        # optional: hook for audit logging
    ActionFormMixin,      # modal-form action
    ExportMixin,          # built-in Excel export
    APIAdmin,             # core admin
):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
    actions = ["add_remarks"]

    enable_audit_log = True

    @admin.action(description="补充备注")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        status = request.POST.get("status", "")
        return {
            "status": "success",
            "msg": (
                f"Got remarks={remarks!r}, status={status!r}, "
                f"selected {len(list(queryset))} row(s)."
            ),
        }

    add_remarks.layer = {
        "title": "补充备注",
        "width": "480px",
        "params": [
            {"type": "input", "key": "remarks",
             "label": "备注说明", "require": True},
            {"type": "radio", "key": "status",
             "label": "是否异常",
             "options": [
                 {"key": "是", "label": "是"},
                 {"key": "否", "label": "否"},
             ]},
        ],
    }

    def log_query(self, request, model_name):
        LogEntry.objects.create(
            action_flag=CHANGE,
            user=request.user,
            change_message="changelist query",
            content_type=ContentType.objects.get(model=model_name),
        )
```

**30 lines of admin config** →

- Paginated, filterable, searchable, sortable changelist
- 5-min Redis cache (optional)
- Excel export
- Custom Modal-form action
- Audit log

That's the **"zero-friction internal tool"** pattern in one file.

---

## What's next

- **Deploy**: this is just a Django project. `gunicorn myproject.wsgi`,
  put nginx in front, set `DEBUG=False`, done.
- **Multiple APIs**: register as many `APIModel` subclasses as you
  want. Each gets its own admin page; they share the same framework.
- **100k+ datasets**: see the `M2_*_DONE.md` files for the
  server-side `/distinct` pattern, the `filter_distinct_limit`
  cap, and the X-Total-Count paginator integration.
