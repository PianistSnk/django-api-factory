"""Admin registrations for the local-mock example.

5 admin pages, all backed by the same local mock server:

- **BigPost** — 100k rows, server-side pagination, cross-page filter,
  X-Total-Count paginator. The M2 performance showcase.
- **PostBare / PostData / PostItems / PostResults** — same dataset
  (default 100 rows) under 4 different envelope shapes. Proves
  `APIModel.parse_response` auto-handles all 4 with no override.

Each admin uses `get_list_display` to build the column list
dynamically from the API's actual response fields (the API fields
aren't Django model fields, so we can't list them in `list_display`
directly without breaking Django's startup check).
"""

from django.contrib import admin
from django.contrib.admin.utils import lookup_field

from django_api_factory.admin import APIAdmin

from .models import BigPost, PostBare, PostData, PostItems, PostResults


def _get_list_display(admin_self, request):
    """Shared get_list_display for all 5 admins in this example."""
    if not admin_self.api_list:
        admin_self.api_data, admin_self.api_list = admin_self.get_api_data(request)
    admin_self.export_list = admin_self.api_list
    valid = ["__str__"]
    for f in admin_self.api_list:
        try:
            lookup_field(f, admin_self.model, admin_self)
            valid.append(f)
        except Exception:
            pass
    return valid


@admin.register(BigPost)
class BigPostAdmin(APIAdmin):
    """100k rows from the local mock server. Server-side pagination,
    X-Total-Count paginator, cross-page filter (all served by the
    mock server). `expected_total = 100_000` so the paginator knows
    how many pages to render."""
    list_display_links = ["__str__"]
    list_per_page = 200
    expected_total = 100_000
    list_filter = []  # default APIFilter auto-generated per field
    get_list_display = _get_list_display

    # 5-min cache on the per-field distinct values (used by the
    # filter dropdowns). The dataset is static, so 5 min is plenty.
    filter_distinct_cache_ttl = 300
    # Cap the dropdown at 200 values so HTML doesn't explode to 41MB
    # (the full enum is still cached server-side; use the search box
    # to find values outside the top 200).
    filter_distinct_limit = 200

    def get_filter_choices(self, field_name, request, q="", offset=0, limit=200):
        """Fetch distinct values from the mock server.

        BigPost has 100k rows, so the generic fallback intentionally refuses
        to scan every page. The mock server exposes `/distinct`, which gives
        the filter UI true cross-page options plus search/load-more.
        """
        admin_limit = getattr(self, "filter_distinct_limit", 0) or limit
        effective_limit = min(limit, admin_limit)

        import hashlib
        import json
        import requests

        qh = hashlib.md5(
            f"{field_name}|{q}|{effective_limit}|{offset}".encode("utf-8")
        ).hexdigest()[:12]
        cache_key = f"distinct:local-mock:{self.model._meta.label_lower}:{qh}"
        if self.filter_distinct_cache_ttl and self.cache_backend is not None:
            try:
                cached = self.cache_backend.get(cache_key)
                if cached:
                    return json.loads(cached.decode("utf-8"))
            except Exception:
                pass

        base = self.model.urls(page=1, page_size=1).split("/posts")[0]
        url = f"{base}/distinct?field={field_name}&limit={effective_limit}&offset={offset}"
        if q:
            from urllib.parse import quote
            url += f"&q={quote(str(q), safe='')}"
        try:
            response = requests.get(url, timeout=self.request_timeout)
            if response.status_code != 200:
                return None
            payload = response.json()
        except Exception:
            return None

        if self.filter_distinct_cache_ttl and self.cache_backend is not None:
            try:
                self.cache_backend.set(
                    cache_key,
                    json.dumps(payload).encode("utf-8"),
                    self.filter_distinct_cache_ttl,
                )
            except Exception:
                pass
        return payload


class _EnvelopeShapeAdmin(APIAdmin):
    """Shared base for the 4 envelope demo admins — proves that
    `APIModel.parse_response` auto-handles all 4 industry-standard
    shapes with zero per-admin override."""
    list_display_links = ["__str__"]
    list_per_page = 50
    list_filter = []
    expected_total = 100
    get_list_display = _get_list_display


@admin.register(PostBare)
class PostBareAdmin(_EnvelopeShapeAdmin):
    """Envelope: bare list — REST canonical."""
    pass


@admin.register(PostData)
class PostDataAdmin(_EnvelopeShapeAdmin):
    """Envelope: {"data": [...]}."""
    pass


@admin.register(PostItems)
class PostItemsAdmin(_EnvelopeShapeAdmin):
    """Envelope: {"items": [...]}."""
    pass


@admin.register(PostResults)
class PostResultsAdmin(_EnvelopeShapeAdmin):
    """Envelope: {"results": [...]} (DRF default)."""
    pass
