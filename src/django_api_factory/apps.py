"""App config for django-api-factory."""

from django.apps import AppConfig


class DjangoApiFactoryConfig(AppConfig):
    name = "django_api_factory"
    verbose_name = "Django API Factory"
    default_auto_field = "django.db.models.BigAutoField"
