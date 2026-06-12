from django.db import models
from abc import abstractmethod


class APIModel(models.Model):
    """
    Abstract base for models that source their data from a REST API.

    Subclasses must implement:
    - urls(**kwargs) -> str: full URL (with query parameters if needed)
    - cache(**kwargs) -> str | None: Redis cache key, or None to disable

    Subclasses may override:
    - black_fields: list of field names to hide from the admin
    - parse_response(response_data) -> list[dict]: convert raw API response
      body into a list of row dicts. Default handles 4 industry-standard
      envelope shapes; override for anything exotic.

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

    black_fields = ["id"]  # type: list[str]
    input_date = models.CharField(
        max_length=255,
        verbose_name="日期 yyyymmdd",
        blank=True,
        default="",
    )

    class Meta:
        abstract = True
        managed = False

    @classmethod
    @abstractmethod
    def urls(cls, **kwargs) -> str:
        """Return the full API URL to fetch data from."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def cache(cls, **kwargs):
        """Return the Redis cache key, or None to disable caching."""
        raise NotImplementedError

    @classmethod
    def parse_response(cls, response_data) -> list:
        """Convert a raw API response body to a list of row dicts.

        We support 4 industry-standard response shapes, in this priority
        order (first match wins):

        1. Bare list:              ``[{...}, {...}]``            (REST canonical)
        2. ``{"data": [...]}``     (common in custom Laravel / internal APIs)
        3. ``{"items": [...]}``    (older JSONPlaceholder / internal APIs)
        4. ``{"results": [...]}``  (Django REST Framework ``PageNumberPagination`` default)

        Why these 4 and not more: they cover the formats used by jsonplaceholder,
        GitHub, Stripe, Google Cloud, and the DRF ecosystem. We deliberately
        do NOT invent a 5th canonical key (e.g. ``payload``, ``rows``, ``list``)
        — if your API uses something exotic, override this method on your
        ``APIModel`` subclass.

        Recommended: write REST-compliant APIs that return a bare list. This
        is the path taken by jsonplaceholder, GitHub, Stripe, and Google Cloud
        — and it removes the need for any unwrapping logic on the client side.

        Override example::

            class MyModel(APIModel):
                @classmethod
                def parse_response(cls, data):
                    if isinstance(data, list):
                        return data
                    return data.get("payload", {}).get("rows", [])
        """
        if isinstance(response_data, list):
            return response_data
        if isinstance(response_data, dict):
            for key in ("data", "items", "results"):
                value = response_data.get(key)
                if isinstance(value, list):
                    return value
        raise ValueError(
            f"{cls.__name__}.parse_response() 收到无法识别的响应格式。"
            f"支持 4 种业界标准格式: 顶层 list / "
            f"{{data: [...]}} / {{items: [...]}} / {{results: [...]}}。"
            f"收到: {type(response_data).__name__} (前 200 字符: "
            f"{str(response_data)[:200]!r})。"
            f"如果是 envelope 格式, override APIModel.parse_response 自己处理。"
            f"参考: {cls.__name__}.urls() 的写法。"
        )

    def __str__(self):
        return str(self.id)
