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

    def __str__(self):
        return str(self.id)
