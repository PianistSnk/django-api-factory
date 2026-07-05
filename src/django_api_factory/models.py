import json

from django.db import models


class APIModel(models.Model):
    """
    Abstract base for models that source their data from a REST API.

    Subclasses normally only need:
    - url / api_url: full URL for simple APIs; OR override urls(**kwargs)
      when the API needs custom pagination/filter query construction

    Subclasses may override:
    - cache(**kwargs) -> str | None: Redis cache key. Default disables cache.
    - parse_response(response_data) -> list[dict]: convert raw API response
      body into a list of row dicts. Default handles common envelope shapes,
      can infer a single list-valued top-level key, and flattens nested dicts.

    Permissions:
        APIModel subclasses are admin-only data viewers — the data lives
        in someone else's REST endpoint, not in our database, so users
        cannot add / change / delete API-sourced rows. We auto-generate
        ONLY the `view_<modelname>` permission; the add / change / delete
        ones are removed in `apps.DjangoApiFactoryConfig.ready()` via a
        `post_migrate` signal handler.

        Why post_migrate and not Meta.default_permissions: Django 5.2
        hardcodes `default_permissions` to `('add', 'change', 'delete',
        'view')` in `Options.__init__` and ignores the `Meta.default_permissions`
        field. The post_migrate approach is the documented way to trim
        the auto-generated permission set.
    """

    #: Fixed URL for simple read-only APIs.
    url = None

    #: Alias for `url`; use it when `url` would conflict in project style.
    api_url = None

    #: Preferred top-level keys that may contain response rows.
    response_list_keys = ("data", "items", "results", "rows", "records")

    #: If True, nested dicts in each response row become flat field names.
    flatten_response_rows = True

    #: Separator inserted between nested field names; empty means camelCase.
    nested_field_separator = ""

    #: Separator used when a list of primitive values is rendered as text.
    list_value_separator = "\u3001"

    #: Synthetic date field kept for compatibility with Django admin search.
    input_date = models.CharField(
        max_length=255,
        verbose_name="Date yyyymmdd",
        blank=True,
        default="",
    )

    class Meta:
        abstract = True
        managed = False

    @classmethod
    def urls(cls, **kwargs) -> str:
        """Return the full API URL to fetch data from.

        For simple APIs, set `url = "https://..."` on the subclass. Override
        this method only when page/page_size/filter kwargs must be translated
        into the API's own query parameter format.
        """
        url = getattr(cls, "api_url", None) or getattr(cls, "url", None)
        if url:
            return url
        raise NotImplementedError(
            f"{cls.__name__} must define `url`/`api_url` or override urls()."
        )

    @classmethod
    def cache(cls, **kwargs):
        """Return the Redis cache key, or None to disable caching."""
        return None

    @classmethod
    def parse_response(cls, response_data) -> list:
        """Convert a raw API response body to a list of row dicts.

        We support common response shapes, in this priority
        order (first match wins):

        1. Bare list:              ``[{...}, {...}]``            (REST canonical)
        2. ``{"data": [...]}``     (common in custom Laravel / internal APIs)
        3. ``{"items": [...]}``    (older JSONPlaceholder / internal APIs)
        4. ``{"results": [...]}``  (Django REST Framework pagination default)
        5. ``{"rows": [...]}`` / ``{"records": [...]}``
        6. Any response with exactly one top-level list value, e.g.
           ``{"users": [...], "total": 208}``

        Nested dict rows are flattened by default, so
        ``{"company": {"name": "Acme"}}`` becomes ``{"companyName": "Acme"}``.

        Recommended: write REST-compliant APIs that return a bare list. This
        is the path taken by jsonplaceholder, GitHub, Stripe, and Google Cloud
        — and it removes the need for any unwrapping logic on the client side.

        Override example for truly custom shapes::

            class MyModel(APIModel):
                @classmethod
                def parse_response(cls, data):
                    if isinstance(data, list):
                        return data
                    return data.get("payload", {}).get("rows", [])
        """
        rows = cls._extract_response_rows(response_data)
        if not getattr(cls, "flatten_response_rows", True):
            return rows
        flattened_rows = []
        changed = False
        for row in rows:
            flattened = cls.flatten_response_row(row)
            flattened_rows.append(flattened)
            changed = changed or flattened is not row
        return flattened_rows if changed else rows

    @classmethod
    def _extract_response_rows(cls, response_data) -> list:
        """Return the row list from a supported response envelope."""
        if isinstance(response_data, list):
            return response_data
        if isinstance(response_data, dict):
            for key in cls.response_list_keys:
                value = response_data.get(key)
                if key in response_data:
                    if isinstance(value, list):
                        return value
                    break
            list_keys = [
                key for key, value in response_data.items()
                if isinstance(value, list)
            ]
            if len(list_keys) == 1:
                return response_data[list_keys[0]]
        raise ValueError(
            f"{cls.__name__}.parse_response() received an unsupported "
            f"response shape. Supported shapes: top-level list / "
            f"{{data: [...]}} / {{items: [...]}} / "
            f"{{results: [...]}} / {{rows: [...]}} / {{records: [...]}} / "
            f"a single top-level list field. Received: "
            f"{type(response_data).__name__} (first 200 chars: "
            f"{str(response_data)[:200]!r}). Override "
            f"APIModel.parse_response for deeper custom envelopes."
        )

    @classmethod
    def flatten_response_row(cls, row):
        """Flatten one API row into admin-friendly scalar fields."""
        if not isinstance(row, dict):
            return row

        flat = {}
        changed = False

        def walk(prefix, value):
            nonlocal changed
            if isinstance(value, dict):
                changed = True
                if not value:
                    flat[prefix] = {}
                    return
                for child_key, child_value in value.items():
                    walk(cls._join_nested_field(prefix, child_key), child_value)
                return
            normalized = cls._normalize_response_value(value)
            if normalized is not value:
                changed = True
            flat[prefix] = normalized

        for key, value in row.items():
            if isinstance(value, dict):
                changed = True
                if not value:
                    flat[key] = {}
                    continue
                for child_key, child_value in value.items():
                    walk(cls._join_nested_field(key, child_key), child_value)
            else:
                normalized = cls._normalize_response_value(value)
                if normalized is not value:
                    changed = True
                flat[key] = normalized

        return flat if changed else row

    @classmethod
    def _join_nested_field(cls, prefix, key):
        """Build a field name for a nested response key."""
        key = str(key)
        if not prefix:
            return key
        separator = getattr(cls, "nested_field_separator", "")
        if separator:
            return f"{prefix}{separator}{key}"
        return f"{prefix}{key[:1].upper()}{key[1:]}"

    @classmethod
    def _normalize_response_value(cls, value):
        """Convert list values to deterministic text for display/filtering."""
        if isinstance(value, list):
            if all(not isinstance(item, (dict, list)) for item in value):
                return getattr(cls, "list_value_separator", "\u3001").join(
                    str(item) for item in value
                )
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    def __str__(self):
        """Return the API row identifier as the admin object label."""
        return str(self.id)
