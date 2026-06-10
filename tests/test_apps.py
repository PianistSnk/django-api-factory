"""Tests for apps.py (Django AppConfig)."""

import pytest
from django.apps import apps


def test_django_api_factory_config_is_registered():
    """The app's AppConfig is auto-discovered via default_app_config."""
    from django_api_factory.apps import DjangoApiFactoryConfig
    config = apps.get_app_config("django_api_factory")
    assert isinstance(config, DjangoApiFactoryConfig)


def test_app_config_attributes():
    from django_api_factory.apps import DjangoApiFactoryConfig
    config = DjangoApiFactoryConfig.create("django_api_factory")
    assert config.name == "django_api_factory"
    assert config.verbose_name == "Django API Factory"
    assert config.default_auto_field == "django.db.models.BigAutoField"
