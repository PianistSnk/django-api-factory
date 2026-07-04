"""Models for the local-mock example.

Two data sources live here:
- local `spikes/big-data-mock/server.py` for the **100k row** M2
  performance and envelope-shape demos;
- real DummyJSON users for a small wide external API.

Together they exercise server-side pagination, dynamic totals, wide
schemas, and `APIModel.parse_response` against realistic response shapes.

To start the mock server (separate terminal):
    cd /path/to/django-api-factory
    python spikes/big-data-mock/server.py --port 8200 --rows 100000
"""

from urllib.parse import quote

from django_api_factory.models import APIModel


# --- BigPost: the 100k-row performance demo ----------------------------


class BigPost(APIModel):
    """100k posts from the local mock server. The M2 performance
    showcase — server-side pagination, cross-page filter, X-Total-Count
    paginator integration.

    The mock server accepts the same `?_page=N&_limit=M` shape as
    JSONPlaceholder, AND supports `?userId=N&title=...&body=...&id=N`
    server-side filter (returns the filtered slice with the right
    X-Total-Count header). Forwarding all kwargs here is what makes
    cross-page filter work — without it, only the current page's
    rows are filtered.
    """

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        qs_parts = [f"_page={page}", f"_limit={page_size}"]
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts?" + "&".join(qs_parts)

    @classmethod
    def cache(cls, **kwargs):
        # Disable cache for the perf demo — we want to measure raw
        # network + admin render cost, not cache hit.
        return None

    class Meta(APIModel.Meta):
        verbose_name = "大数据 Post (M2 spike)"
        verbose_name_plural = "大数据 Post (M2 spike)"


class DummyJSONUser(APIModel):
    """Real public API demo backed by DummyJSON users."""

    url = "https://dummyjson.com/users?limit=1000"

    class Meta(APIModel.Meta):
        verbose_name = "真实 DummyJSON 用户 API (wide)"
        verbose_name_plural = "真实 DummyJSON 用户 API (wide)"


def _mock_url(path: str, page: int, page_size: int, **kwargs) -> str:
    """Build a URL for mock endpoints that use page/page_size params."""
    qs = [f"page={page}", f"page_size={page_size}"]
    for k, v in kwargs.items():
        if v in (None, ""):
            continue
        qs.append(f"{k}={quote(str(v), safe='')}")
    return f"http://127.0.0.1:8200/{path}?" + "&".join(qs)


# --- Envelope-shape demo models (Jun 2026 — APIModel.parse_response)
# The local mock server exposes the same dataset under common envelope
# shapes so we can verify APIModel.parse_response handles wrappers with
# the default impl (no override required).


class PostBare(APIModel):
    """Envelope shape #1: bare list (REST canonical)."""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        return _mock_url("posts-bare", page, page_size, **kwargs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: bare list)"
        verbose_name_plural = "Post (envelope: bare list)"


class PostData(APIModel):
    """Envelope shape #2: {"data": [...]} (Laravel / internal APIs)."""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        return _mock_url("posts-data", page, page_size, **kwargs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {data: [...]})"
        verbose_name_plural = "Post (envelope: {data: [...]})"


class PostItems(APIModel):
    """Envelope shape #3: {"items": [...]} (older internal APIs)."""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        return _mock_url("posts-items", page, page_size, **kwargs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {items: [...]})"
        verbose_name_plural = "Post (envelope: {items: [...]})"


class PostResults(APIModel):
    """Envelope shape #4: {"results": [...]} (Django REST Framework)."""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        return _mock_url("posts-results", page, page_size, **kwargs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {results: [...]})"
        verbose_name_plural = "Post (envelope: {results: [...]})"
