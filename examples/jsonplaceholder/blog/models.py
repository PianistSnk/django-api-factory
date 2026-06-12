"""Models for the jsonplaceholder example.

Sourced from JSONPlaceholder (https://jsonplaceholder.typicode.com/),
a public fake REST API. This is the "hello world" data source for
django-api-factory — no auth, no rate limits, perfect for getting
started.

Each `APIModel` subclass declares two things:
- `urls(**kwargs)` — the URL to GET (kwargs include `page`, `page_size`,
  and any filter / sort params the admin forwards).
- `cache(**kwargs)` — a Redis key prefix, or `None` to disable caching.
"""

from urllib.parse import quote

from django_api_factory.models import APIModel


class Post(APIModel):
    """A blog post from JSONPlaceholder /posts."""

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        # Base pagination query (JSONPlaceholder uses _page / _limit).
        qs_parts = [f"_page={page}", f"_limit={page_size}"]
        # Forward any extra kwargs as query params so the API applies
        # them server-side (e.g. `?userId=1` returns only that user's
        # posts). See Tutorial 2 for the full cross-page filter pattern.
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        return "https://jsonplaceholder.typicode.com/posts?" + "&".join(qs_parts)

    @classmethod
    def cache(cls, **kwargs):
        # None = no Redis caching. Opt in with `cache_backend_class =
        # RedisCacheBackend` on the admin if you want it.
        return None

    class Meta(APIModel.Meta):
        verbose_name = "博客文章 (JSONPlaceholder)"
        verbose_name_plural = "博客文章 (JSONPlaceholder)"


class User(APIModel):
    """A user from JSONPlaceholder /users."""

    @classmethod
    def urls(cls, **kwargs) -> str:
        return "https://jsonplaceholder.typicode.com/users"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        verbose_name = "用户 (JSONPlaceholder)"
        verbose_name_plural = "用户 (JSONPlaceholder)"
