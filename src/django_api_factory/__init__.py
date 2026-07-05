"""django-api-factory: Display external REST API data in Django admin."""

__version__ = "0.1.1"

# Imports are kept lazy so the package can be added to INSTALLED_APPS without
# triggering model class creation before Django's app registry is ready.
# Use `from django_api_factory import APIModel, APIAdmin, ...` after Django
# has been set up (i.e. after django.setup() in management commands and tests).
default_app_config = "django_api_factory.apps.DjangoApiFactoryConfig"

__all__ = [
    "APIModel",
    "APIAdmin",
    "APINoDataAdmin",
    "APIFilter",
    "APIChangeList",
    "MyQuerySet",
]
