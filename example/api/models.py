"""Models for the example project.

Sourced from JSONPlaceholder (Post, User) for the standard demo,
plus BigPost for the M2 spike — points at the local mock server
(`spikes/big-data-mock/server.py`) which serves configurable row
counts (1w / 10w / 100w) to stress-test the admin.
"""

from django_api_factory.models import APIModel


class Post(APIModel):
    """
    A Post sourced from JSONPlaceholder — a public fake REST API.

    The two abstract methods you MUST implement:
    - urls():  return the full URL to GET
    - cache(): return a Redis key prefix (or None to disable caching)
    """

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        # M2 server-side pagination: API returns only the current page.
        # Cross-page filter (Jun 2026): forward any extra kwargs as
        # query params so JSONPlaceholder applies them server-side
        # (e.g. `?userId=1&_page=1&_limit=10` returns only userId=1 rows).
        # Without this forwarding, the admin would have to client-side
        # filter the current page only — wrong for any p > 1.
        from urllib.parse import quote
        qs_parts = [f"_page={page}", f"_limit={page_size}"]
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        return "https://jsonplaceholder.typicode.com/posts?" + "&".join(qs_parts)

    @classmethod
    def cache(cls, **kwargs):
        # Returning None disables Redis caching for this model.
        return None

    class Meta(APIModel.Meta):
        verbose_name = "博客文章 (JSONPlaceholder)"
        verbose_name_plural = "博客文章 (JSONPlaceholder)"


class User(APIModel):
    """A User sourced from JSONPlaceholder."""

    @classmethod
    def urls(cls, **kwargs) -> str:
        return "https://jsonplaceholder.typicode.com/users"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "用户 (JSONPlaceholder)"
        verbose_name_plural = "用户 (JSONPlaceholder)"


class BigPost(APIModel):
    """A Post sourced from the local M2 spike mock server.

    `spikes/big-data-mock/server.py` serves configurable row counts
    on http://127.0.0.1:8200/posts. Used to benchmark the admin
    against 1w / 10w / 100w row datasets.
    """

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        # Mock server accepts the same `?_page=N&_limit=M` shape as
        # JSONPlaceholder, AND supports `?userId=N&title=...&body=...`
        # server-side filter (returns the filtered slice with the right
        # X-Total-Count header). Forwarding all kwargs here is what
        # makes cross-page filter work — without it, only the current
        # page's rows are filtered.
        from urllib.parse import quote
        qs_parts = [f"_page={page}", f"_limit={page_size}"]
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts?" + "&".join(qs_parts)

    @classmethod
    def cache(cls, **kwargs):
        # Disable cache for spike — we want to measure raw network
        # + admin render cost, not cache hit.
        return None

    class Meta(APIModel.Meta):
        verbose_name = "大数据 Post (M2 spike)"
        verbose_name_plural = "大数据 Post (M2 spike)"


# --- Jun 2026: 4 envelope-shape demo models ------------------------------
# The local mock server (`spikes/big-data-mock/server.py`) exposes the
# same dataset under 4 different envelope shapes so we can verify
# APIModel.parse_response handles all 4 with the default impl (no
# override required). Each model points at a different /posts-XYZ path
# and inherits the same default parse_response, but routes the URL to a
# different envelope. Together they prove "one admin can speak 4 industry
# response shapes without per-admin boilerplate".


class PostBare(APIModel):
    """Envelope shape #1: bare list (REST canonical — jsonplaceholder etc.)"""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        from urllib.parse import quote
        qs = [f"page={page}", f"page_size={page_size}"]
        for k, v in kwargs.items():
            if v in (None, ""):
                continue
            qs.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts-bare?" + "&".join(qs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: bare list)"
        verbose_name_plural = "Post (envelope: bare list)"


class PostData(APIModel):
    """Envelope shape #2: {"data": [...]} (Laravel / internal APIs)"""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        from urllib.parse import quote
        qs = [f"page={page}", f"page_size={page_size}"]
        for k, v in kwargs.items():
            if v in (None, ""):
                continue
            qs.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts-data?" + "&".join(qs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {data: [...]})"
        verbose_name_plural = "Post (envelope: {data: [...]})"


class PostItems(APIModel):
    """Envelope shape #3: {"items": [...]} (older internal APIs)"""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        from urllib.parse import quote
        qs = [f"page={page}", f"page_size={page_size}"]
        for k, v in kwargs.items():
            if v in (None, ""):
                continue
            qs.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts-items?" + "&".join(qs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {items: [...]})"
        verbose_name_plural = "Post (envelope: {items: [...]})"


class PostResults(APIModel):
    """Envelope shape #4: {"results": [...]} (Django REST Framework)"""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        from urllib.parse import quote
        qs = [f"page={page}", f"page_size={page_size}"]
        for k, v in kwargs.items():
            if v in (None, ""):
                continue
            qs.append(f"{k}={quote(str(v), safe='')}")
        return "http://127.0.0.1:8200/posts-results?" + "&".join(qs)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "Post (envelope: {results: [...]})"
        verbose_name_plural = "Post (envelope: {results: [...]})"
