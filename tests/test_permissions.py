"""Tests for APIModel's permission setup.

APIModel subclasses are admin-only data viewers — the data lives in someone
else's REST endpoint, not in our database, so users cannot add / change /
delete API-sourced rows. We trim Django's auto-generated permission set
to `view_<modelname>` only via a `post_migrate` signal handler in
`apps.DjangoApiFactoryConfig.ready()`.

Why post_migrate and not Meta.default_permissions: Django 5.2 hardcodes
`default_permissions` to `('add', 'change', 'delete', 'view')` in
`Options.__init__` and ignores the `Meta.default_permissions` field. The
post_migrate approach is the documented way to trim the auto-generated
set.
"""

import pytest
from django.apps import apps
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from django_api_factory.models import APIModel


@pytest.fixture
def django_permissions(db):
    """Django auto-generates per-model Permission rows in the `post_migrate`
    signal via `create_permissions`. pytest-django's `db` fixture doesn't
    trigger that, so the Permission table is empty in unit tests unless we
    call it ourselves.

    After Django's stock `create_permissions` runs (4 permissions per model:
    add / change / delete / view), our `apps.DjangoApiFactoryConfig`
    `post_migrate` handler strips add / change / delete — leaving only
    `view_<modelname>`. We invoke both here in order.

    Usage:  def test_xyz(django_permissions):
    """
    for app_name in ("auth", "tests"):
        create_permissions(apps.get_app_config(app_name), verbosity=0)
    # Now invoke our own trim — same handler that runs in production.
    from django_api_factory.apps import trim_api_model_permissions
    trim_api_model_permissions()


# --- Concrete subclass permission generation ------------------------------

class PermTestModel(APIModel):
    """Throwaway concrete subclass for permission-content-type lookup."""
    title = ""

    def urls(self, **kwargs):
        return "https://example.com"

    def cache(self, **kwargs):
        return None

    class Meta:
        app_label = "tests"


@pytest.mark.django_db
def test_concrete_subclass_gets_view_permission_only(django_permissions):
    """After `create_permissions` + our trim, only `view_permtestmodel`
    exists for the subclass — no add / change / delete."""
    ct = ContentType.objects.get_for_model(PermTestModel)
    codenames = set(
        Permission.objects.filter(content_type=ct).values_list("codename", flat=True)
    )
    assert "view_permtestmodel" in codenames
    # The other three are NOT present (the post_migrate handler removed them):
    assert "add_permtestmodel" not in codenames
    assert "change_permtestmodel" not in codenames
    assert "delete_permtestmodel" not in codenames


@pytest.mark.django_db
def test_view_permission_metadata_is_human_readable(django_permissions):
    """The view permission has a Django-conventional name like
    'Can view <verbose_name>' so the admin UI shows something useful."""
    perm = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(PermTestModel),
        codename="view_permtestmodel",
    )
    assert "view" in perm.name.lower()


@pytest.mark.django_db
def test_trim_is_idempotent(django_permissions):
    """Re-running the trim handler should be a no-op (no errors, no
    side effects on the Permission table)."""
    from django_api_factory.apps import trim_api_model_permissions
    trim_api_model_permissions()  # second run

    ct = ContentType.objects.get_for_model(PermTestModel)
    codenames = set(
        Permission.objects.filter(content_type=ct).values_list("codename", flat=True)
    )
    # Still only view; nothing else got created or duplicated.
    assert codenames == {"view_permtestmodel"}


# --- Permission check semantics -------------------------------------------

@pytest.mark.django_db
def test_view_permission_is_checked_via_user_has_perm(django_permissions, django_user_model):
    """The stock Django flow: a user with `view_permtestmodel` in their
    permission set passes `user.has_perm('tests.view_permtestmodel')`."""
    ct = ContentType.objects.get_for_model(PermTestModel)
    perm = Permission.objects.get(
        content_type=ct, codename="view_permtestmodel"
    )
    user = django_user_model.objects.create_user(
        username="viewer", password="x", is_staff=True,
    )
    # Before grant: no access
    assert user.has_perm("tests.view_permtestmodel") is False
    # Grant the single view permission
    user.user_permissions.add(perm)
    user = django_user_model.objects.get(pk=user.pk)  # refresh perm cache
    assert user.has_perm("tests.view_permtestmodel") is True
