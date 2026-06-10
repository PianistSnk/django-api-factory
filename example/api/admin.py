"""M2 spike admin: register BigPost for benchmarking.

Kept minimal — no T1.6 filters, no simpleui, no cache, no actions.
Just enough to measure raw network + render cost at scale.
"""

from django.contrib import admin

from django_api_factory.admin import APIAdmin

from .models import BigPost, Post, User


# --- Re-register Post/User with the same UX as before --------------------
# (Kept here so this file is the single source of truth for example
# admin wiring; the original PostAdmin / UserAdmin definitions live
# in this file too.)

from django_api_factory.filter import APIFilter, APIMultiSelectFilter
from django_api_factory.mixins import RedisCacheBackend


@admin.register(Post)
class PostAdmin(APIAdmin):
    """JSONPlaceholder Post admin — unchanged from M1."""
    change_form_template = "api/change_form_demo.html"
    actions = ["add_remarks"]
    list_display = ["__str__"]
    list_display_links = ["__str__"]
    list_per_page = 10
    list_filter = [
        ("userId", APIFilter),
        ("title", APIFilter),
        ("body", APIMultiSelectFilter),
    ]
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
    detail_cache_enabled = True
    detail_cache_ttl = 300
    expected_total = 100

    def get_list_display(self, request):
        if not self.api_list:
            self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        from django.contrib.admin.utils import lookup_field
        valid = ["__str__"]
        for f in self.api_list:
            try:
                lookup_field(f, self.model, self)
                valid.append(f)
            except Exception:
                pass
        return valid

    @admin.action(description="补充备注")
    def add_remarks(self, request, queryset):
        remarks = request.POST.get("remarks", "")
        status = request.POST.get("status", "")
        return {
            "status": "success",
            "msg": f"Got remarks={remarks!r}, status={status!r}, "
                   f"selected {len(list(queryset))} row(s).",
        }

    add_remarks.icon = "fas fa-edit"
    add_remarks.type = "info"
    add_remarks.style = "color:white"
    add_remarks.layer = {
        "title": "补充备注",
        "width": "480px",
        "params": [
            {"type": "input", "key": "remarks", "label": "备注说明", "require": True},
            {"type": "radio", "key": "status", "label": "是否异常",
             "options": [{"key": "是", "label": "是"}, {"key": "否", "label": "否"}]},
        ],
    }


@admin.register(User)
class UserAdmin(APIAdmin):
    """JSONPlaceholder User admin — unchanged from M1.

    Jun 2026: enable Redis cache like PostAdmin so the framework's
    default `get_filter_choices` (shared raw-rows cache) actually
    caches. Without this, UserAdmin inherits NullCacheBackend and
    re-walks all API pages on every page load — 20+s on first
    render even after the framework's per-field dedup fix.
    """
    list_filter = [
        ("name", APIMultiSelectFilter),
        ("username", APIFilter),
        ("email", APIMultiSelectFilter),
    ]
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = True
    changelist_cache_ttl = 300
    expected_total = 10  # jsonplaceholder /users is 10 rows


# --- M2 spike admin ------------------------------------------------------

@admin.register(BigPost)
class BigPostAdmin(APIAdmin):
    """M2 spike admin — minimal config to isolate benchmark cost.

    Configured for 100k rows by default. Adjust `expected_total` and
    the mock server's --rows flag together to sweep 1k / 1w / 10w / 100w.
    """
    list_display = ["__str__"]
    list_display_links = ["__str__"]
    # 200 per page (Jun 2026: bumped from 50 so the user can sweep
    # the 100k dataset with fewer clicks. /admin/api/bigpost/?p=1
    # fetches 200 rows per request, 500 pages total.)
    list_per_page = 200
    # No manual list_filter — we auto-generate `APIFilter` per API
    # field, and override `get_filter_choices` below so the dropdowns
    # show the FULL enum from the mock server's /distinct endpoint
    # (10_000 userIds, 100_000 titles, ...), not just the 200 values
    # visible on the current page.
    list_filter = []
    # T2.1 fold-down: declare dataset size so paginator can render
    # page links without asking the API for a total.
    expected_total = 100_000  # spike: 1k / 10k / 100k — set this to match mock --rows
    # Disable the Redis cache so we measure network + render, not cache hit.
    cache_backend_class = RedisCacheBackend
    changelist_cache_enabled = False
    detail_cache_enabled = False

    # 5-min TTL on the per-field distinct cache. The dataset is static
    # in the mock, so 5 min is plenty. Production with live data: bump
    # this or set to 0 to disable.
    filter_distinct_cache_ttl = 300
    # Jun 2026 cap: render only the top N distinct values in the
    # filter dropdown. The full enum is still cached server-side in
    # Redis (key includes the limit), so changing this and reloading
    # the page will fetch a different slice. 200 is the sweet spot:
    # - HTML response: ~1MB instead of 41MB
    # - T1.6 client-side search still finds values in the visible 200
    # - Values outside the top 200 are reachable via URL hand-input
    #   (?userId=5000) or future "load more" button.
    filter_distinct_limit = 200

    def get_list_display(self, request):
        if not self.api_list:
            self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        from django.contrib.admin.utils import lookup_field
        valid = ["__str__"]
        for f in self.api_list:
            try:
                lookup_field(f, self.model, self)
                valid.append(f)
            except Exception:
                pass
        return valid

    def get_filter_choices(self, field_name, request, q="", offset=0, limit=200):
        """BigPost override of the generic Jun 2026 hook. Calls
        the mock server's /distinct endpoint with the current
        `q`/`offset`/`limit` so search and load-more both work
        without re-implementing the pagination logic here.

        Cache key includes q so two different search terms don't
        stomp on each other. limit caps the response size (the
        dropdown only shows the first 200 anyway).
        """
        # Honor the admin's filter_distinct_limit if it caps below
        # the requested limit.
        admin_limit = getattr(self, "filter_distinct_limit", 0) or limit
        effective_limit = min(limit, admin_limit)
        # Cache key includes the search term so different queries
        # don't collide. Same q+limit+offset within the TTL window
        # is a hit.
        import hashlib
        qh = hashlib.md5(f"{q}|{effective_limit}|{offset}".encode("utf-8")).hexdigest()[:12]
        cache_key = f"distinct:bp:{self.model._meta.label_lower}:{field_name}:{qh}"
        if self.filter_distinct_cache_ttl and self.cache_backend is not None:
            try:
                cached = self.cache_backend.get(cache_key)
                if cached:
                    import json as _json
                    return _json.loads(cached.decode("utf-8"))
            except Exception:
                pass
        # Cache miss: call mock /distinct with all params
        import requests as _requests
        try:
            base = self.model.urls(page=1, page_size=1).split("/posts")[0]
            url = f"{base}/distinct?field={field_name}&limit={effective_limit}&offset={offset}"
            if q:
                url += f"&q={q}"
            resp = _requests.get(url, timeout=self.request_timeout)
            if resp.status_code == 200:
                import json as _json
                payload = resp.json()
                if self.filter_distinct_cache_ttl and self.cache_backend is not None:
                    try:
                        self.cache_backend.set(
                            cache_key,
                            _json.dumps(payload).encode("utf-8"),
                            self.filter_distinct_cache_ttl,
                        )
                    except Exception:
                        pass
                return payload
        except Exception:
            pass
        return None

    def _filter_distinct_cache_key(self, field_name):
        """Redis key for the per-field distinct values. Includes the
        limit so changing `filter_distinct_limit` doesn't return a
        stale cache entry from the old size."""
        import hashlib
        h = hashlib.md5(field_name.encode("utf-8")).hexdigest()[:12]
        limit = getattr(self, "filter_distinct_limit", 0)
        return f"distinct:{self.model._meta.label_lower}:l{limit}:{h}"
