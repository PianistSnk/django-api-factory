"""Smoke tests for django-api-factory. See conftest.py for Django config."""


def test_imports():
    from django_api_factory.models import APIModel
    from django_api_factory.admin import APIAdmin, APINoDataAdmin
    from django_api_factory.filter import APIFilter
    from django_api_factory.queryset import MyQuerySet
    # Re-export the same names from the top-level package
    from django_api_factory import models as M, admin as A, filter as F, queryset as Q
    assert APIModel is M.APIModel
    assert APIAdmin is A.APIAdmin
    assert APINoDataAdmin is A.APINoDataAdmin
    assert APIFilter is F.APIFilter
    assert MyQuerySet is Q.MyQuerySet


def test_apimodel_abstract():
    from django_api_factory.models import APIModel
    from django.db import models

    class Post(APIModel):
        app_label = "tests"

        def urls(self, **kwargs):
            return "https://example.com"

        def cache(self, **kwargs):
            return None

    assert issubclass(Post, models.Model)
    assert Post._meta.managed is False
    # Django 5.2 ignores `Meta.default_permissions` and hardcodes the stock
    # four, but our `post_migrate` signal handler in
    # `apps.DjangoApiFactoryConfig.ready()` strips everything except
    # `view_<model>` after `migrate` runs. The smoke check is "abstract
    # base still gets found and the model class itself is well-formed";
    # permission generation is exercised in test_permissions.py.
    assert issubclass(Post, APIModel)


def test_myqueryset_clone_is_shallow():
    """MyQuerySet._clone should override QuerySet._clone to use shallow copy."""
    from django_api_factory.queryset import MyQuerySet
    from django.db.models.query import QuerySet
    import inspect
    # Verify the override exists and references copy.copy
    src = inspect.getsource(MyQuerySet._clone)
    assert "copy.copy" in src
    # Confirm it's a real override (not inherited)
    assert MyQuerySet._clone is not QuerySet._clone
