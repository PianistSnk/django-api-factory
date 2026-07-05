"""Admin registrations for the local-mock example.

6 admin pages: one real external API plus five local mock demos:

- **BigPost** — 100k rows, server-side pagination, cross-page filter,
  and X-Total-Count paginator integration.
- **DummyJSONUser** — real public DummyJSON users endpoint, 200-ish
  nested records flattened into 45+ admin columns.
- **PostBare / PostData / PostItems / PostResults** — same dataset
  under 4 common envelope shapes. Proves `APIModel.parse_response`
  auto-handles common wrappers with no override.

Each admin uses Django's native `list_display` to choose visible API
fields and column order.
"""

from django.contrib import admin

from django_api_factory.admin import APIAdmin

from .models import (
    BigPost,
    DummyJSONUser,
    PostBare,
    PostData,
    PostItems,
    PostResults,
)


@admin.register(BigPost)
class BigPostAdmin(APIAdmin):
    """100k rows from the local mock server. Server-side pagination,
    X-Total-Count paginator, cross-page filter (all served by the
    mock server). The paginator reads the live total from the API
    instead of relying on a static expected_total."""
    list_display = ["id", "userId", "title", "body"]
    filter_distinct_resource = "posts"


@admin.register(DummyJSONUser)
class DummyJSONUserAdmin(APIAdmin):
    """Real external REST API demo: DummyJSON users, 45+ flattened fields."""
    list_display = [
        "id",
        "firstName",
        "lastName",
        "age",
        "gender",
        "email",
        "phone",
        "username",
        "companyName",
        "companyTitle",
        "role",
    ]
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


class _EnvelopeShapeAdmin(APIAdmin):
    """Shared base for the 4 envelope demo admins — proves that
    `APIModel.parse_response` auto-handles common wrappers with
    zero per-admin override."""
    list_display = ["id", "userId", "title", "body"]


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
