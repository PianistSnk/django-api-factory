"""App config for django-api-factory."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def iter_api_model_subclasses(model_cls):
    """Yield all concrete APIModel subclasses recursively."""
    for subclass in model_cls.__subclasses__():
        yield from iter_api_model_subclasses(subclass)
        if not subclass._meta.abstract:
            yield subclass


def trim_api_model_permissions(**kwargs):
    """Strip the auto-generated default permissions for APIModel subclasses.

    Django auto-generates `('add', 'change', 'delete', 'view')` permissions
    for every model. APIModel subclasses are read-only (data lives in
    someone else's REST endpoint, not our DB) — we want only
    `view_<model>` to exist, so non-superuser staff can be granted read
    access to the changelist without being able to mutate anything.

    This runs as a `post_migrate` signal handler so the cleanup fires on
    every `migrate` call. Idempotent — re-running just deletes the same
    rows.
    """
    # Imports kept local to avoid AppConfig.ready() import-time issues.
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from django_api_factory.models import APIModel

    for subclass in iter_api_model_subclasses(APIModel):
        ct = ContentType.objects.get_for_model(subclass)
        Permission.objects.filter(content_type=ct).exclude(
            codename__startswith="view_"
        ).delete()


class DjangoApiFactoryConfig(AppConfig):
    name = "django_api_factory"
    verbose_name = "Django API Factory"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        post_migrate.connect(
            trim_api_model_permissions,
            dispatch_uid="django_api_factory.trim_api_model_permissions",
        )
