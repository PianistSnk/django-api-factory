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
        default_permissions = []

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
