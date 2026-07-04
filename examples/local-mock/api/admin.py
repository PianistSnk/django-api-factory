"""Admin registrations for the local-mock example.

6 admin pages: one real external API plus five local mock demos:

- **BigPost** — 100k rows, server-side pagination, cross-page filter,
  X-Total-Count paginator. The M2 performance showcase.
- **DummyJSONUser** — real public DummyJSON users endpoint, 200-ish
  nested records flattened into 45+ admin columns.
- **PostBare / PostData / PostItems / PostResults** — same dataset
  under 4 common envelope shapes. Proves `APIModel.parse_response`
  auto-handles common wrappers with no override.

Each admin uses `get_list_display` to build the column list
dynamically from the API's actual response fields (the API fields
aren't Django model fields, so we can't list them in `list_display`
directly without breaking Django's startup check).
"""

from django.contrib import admin
from django.contrib.admin.utils import lookup_field

from django_api_factory.admin import APIAdmin

from .models import (
    BigPost,
    DummyJSONUser,
    PostBare,
    PostData,
    PostItems,
    PostResults,
)


def _get_list_display(admin_self, request):
    """Shared get_list_display for all 6 admins in this example."""
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
    mock server). The paginator reads the live total from the API
    instead of relying on a static expected_total."""
    list_display_links = ["__str__"]
    filter_distinct_resource = "posts"
    get_list_display = _get_list_display


@admin.register(DummyJSONUser)
class DummyJSONUserAdmin(APIAdmin):
    """Real external REST API demo: DummyJSON users, 45+ flattened fields."""
    list_display_links = ["__str__"]
    list_per_page = 1000
    filter_distinct_max_rows = 1000
    list_filter_exclude = [
        "image",
        "password",
        "ssn",
        "userAgent",
        "bankCardNumber",
        "bankIban",
        "cryptoWallet",
    ]
    get_list_display = _get_list_display


class _EnvelopeShapeAdmin(APIAdmin):
    """Shared base for the 4 envelope demo admins — proves that
    `APIModel.parse_response` auto-handles common wrappers with
    zero per-admin override."""
    list_display_links = ["__str__"]
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
