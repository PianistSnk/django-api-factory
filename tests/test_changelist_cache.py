"""Tests for short-term changelist cache (T1.5b opt-in)."""

import json
import pytest
from unittest.mock import MagicMock

from django_api_factory.admin import APIAdmin
from django_api_factory.models import APIModel
from django_api_factory.mixins import BaseCacheBackend, NullCacheBackend, schema_registry


# --- Test fixtures --------------------------------------------------------

class ChangelistItem(APIModel):
    app_label = "tests"

    @classmethod
    def urls(cls, **kwargs):
        return "https://example.com"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta:
        app_label = "tests"


class InMemoryCacheBackend(BaseCacheBackend):
    def __init__(self):
        self._data: dict = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl):
        self._data[key] = value

    def delete(self, key):
        self._data.pop(key, None)


@pytest.fixture
def admin_inst():
    """APIAdmin with InMemoryCacheBackend and changelist cache enabled."""
    inst = APIAdmin.__new__(APIAdmin)
    inst.model = ChangelistItem
    if hasattr(inst, "_cache_backend_inst"):
        del inst._cache_backend_inst
    inst._cache_backend_inst = InMemoryCacheBackend()
    # Default values matching production behavior
    inst.changelist_cache_enabled = True
    inst.changelist_cache_ttl = 300
    inst.detail_cache_enabled = False
    inst.detail_cache_ttl = 300
    inst.cache_backend_class = NullCacheBackend
    schema_registry.reset()
    return inst


# --- _changelist_cache_key ------------------------------------------------

def test_changelist_cache_key_differs_from_detail(admin_inst):
    """Same request, different key prefix — no collision if both enabled."""
    from django.test import RequestFactory
    req = RequestFactory().get("/admin/tests/changelistitem/?q=foo")
    req.user = type("U", (), {"pk": 1})()
    detail_key = admin_inst._detail_cache_key(req)
    changelist_key = admin_inst._changelist_cache_key(req)
    assert "detail:" in detail_key
    assert "changelist:" in changelist_key
    assert detail_key != changelist_key


def test_changelist_cache_key_includes_pagination_and_per_page(admin_inst):
    """T2.1 (F4): under server-side pagination, each page is a separate
    API call, so `p` and `per_page` ARE part of the cache key.
    Different page = different cache entry = fresh API call.

    Same-page repeat clicks (5-min TTL) still hit cache — only
    page/per_page CHANGES trigger a fresh fetch."""
    from django.test import RequestFactory
    req1 = RequestFactory().get("/admin/tests/changelistitem/?p=1&per_page=10&o=1.0")
    req1.user = type("U", (), {"pk": 1})()
    req2 = RequestFactory().get("/admin/tests/changelistitem/?p=2&per_page=20&o=1.0")
    req2.user = type("U", (), {"pk": 1})()
    # `p` and `per_page` differ → different cache key. The user's
    # `o=1.0` sort is the same, but p/per_page shape a different slice.
    assert admin_inst._changelist_cache_key(req1) != admin_inst._changelist_cache_key(req2)


def test_changelist_cache_key_same_page_repeats_hit(admin_inst):
    """Same page + same per_page + same sort + same filters + same
    user = SAME cache key. The whole point of the 5-min TTL cache —
    user clicks twice within 5 min, second click doesn't hit API."""
    from django.test import RequestFactory
    req1 = RequestFactory().get("/admin/tests/changelistitem/?p=3&per_page=50&o=1.0")
    req1.user = type("U", (), {"pk": 1})()
    req2 = RequestFactory().get("/admin/tests/changelistitem/?p=3&per_page=50&o=1.0")
    req2.user = type("U", (), {"pk": 1})()
    assert admin_inst._changelist_cache_key(req1) == admin_inst._changelist_cache_key(req2)


def test_changelist_cache_key_scopes_by_user_and_model(admin_inst):
    from django.test import RequestFactory
    req_a = RequestFactory().get("/admin/tests/changelistitem/")
    req_a.user = type("U", (), {"pk": 1})()
    req_b = RequestFactory().get("/admin/tests/changelistitem/")
    req_b.user = type("U", (), {"pk": 2})()
    # Same params, different user = different key
    assert admin_inst._changelist_cache_key(req_a) != admin_inst._changelist_cache_key(req_b)


# --- Opt-in behavior ------------------------------------------------------

def test_default_is_disabled():
    """APIAdmin default: changelist_cache_enabled = False."""
    assert APIAdmin.changelist_cache_enabled is False


def test_default_is_disabled_detail():
    """APIAdmin default: detail_cache_enabled = False (also opt-in now)."""
    assert APIAdmin.detail_cache_enabled is False


# --- Cache write on get_api_data ------------------------------------------

def test_get_api_data_writes_changelist_cache_when_enabled(admin_inst, monkeypatch):
    """get_api_data should write to changelist cache when enabled."""
    # Stub out the network call so get_api_data returns a known shape
    from django.test import RequestFactory
    from unittest.mock import patch

    sample = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = json.dumps(sample).encode("utf-8")

    with patch("django_api_factory.admin.requests.get", return_value=fake_response):
        req = RequestFactory().get("/admin/tests/changelistitem/")
        req.user = type("U", (), {"pk": 1})()
        admin_inst.get_api_data(req)

    # Cache should now contain our sample under the changelist key
    key = admin_inst._changelist_cache_key(req)
    cached = admin_inst.cache_backend.get(key)
    assert cached is not None
    assert json.loads(cached) == sample


def test_get_api_data_does_not_write_changelist_cache_when_disabled(admin_inst):
    """When changelist_cache_enabled = False, nothing is written."""
    admin_inst.changelist_cache_enabled = False

    from django.test import RequestFactory
    from unittest.mock import patch

    sample = [{"id": 1, "name": "Alice"}]
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = json.dumps(sample).encode("utf-8")

    with patch("django_api_factory.admin.requests.get", return_value=fake_response):
        req = RequestFactory().get("/admin/tests/changelistitem/")
        req.user = type("U", (), {"pk": 1})()
        admin_inst.get_api_data(req)

    key = admin_inst._changelist_cache_key(req)
    assert admin_inst.cache_backend.get(key) is None


def test_changelist_cache_ttl_zero_disables_write(admin_inst):
    """changelist_cache_ttl=0 means get_api_data skips the write."""
    admin_inst.changelist_cache_ttl = 0

    from django.test import RequestFactory
    from unittest.mock import patch

    sample = [{"id": 1}]
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = json.dumps(sample).encode("utf-8")

    with patch("django_api_factory.admin.requests.get", return_value=fake_response):
        req = RequestFactory().get("/admin/tests/changelistitem/")
        req.user = type("U", (), {"pk": 1})()
        admin_inst.get_api_data(req)

    key = admin_inst._changelist_cache_key(req)
    assert admin_inst.cache_backend.get(key) is None


# --- Cache read in get_api_data -------------------------------------------

def test_get_api_data_reads_changelist_cache_when_enabled(admin_inst, monkeypatch):
    """When cache has data, get_api_data returns it without calling the API."""
    from django.test import RequestFactory
    from unittest.mock import patch

    # Pre-populate the cache
    sample = [{"id": 1, "name": "from-cache"}, {"id": 2, "name": "also-cache"}]
    req = RequestFactory().get("/admin/tests/changelistitem/")
    req.user = type("U", (), {"pk": 1})()
    admin_inst.cache_backend.set(
        admin_inst._changelist_cache_key(req),
        json.dumps(sample).encode("utf-8"),
        300,
    )

    # If get_api_data still calls the API, this patch will fail the test
    def fail_if_called(*args, **kwargs):
        raise AssertionError("requests.get was called but should have hit the cache")
    with patch("django_api_factory.admin.requests.get", side_effect=fail_if_called):
        mymodels_qs, fields = admin_inst.get_api_data(req)
    # Sanity check: the cached sample is what came back
    items = list(mymodels_qs)
    assert len(items) == 2
    assert items[0].name == "from-cache"
    assert items[1].name == "also-cache"


def test_get_api_data_skips_cache_when_disabled(admin_inst, monkeypatch):
    """When changelist_cache_enabled = False, get_api_data hits the API."""
    admin_inst.changelist_cache_enabled = False
    from django.test import RequestFactory
    from unittest.mock import patch

    # Pre-populate the cache (should be ignored)
    sample = [{"id": 1, "name": "ignored"}]
    req = RequestFactory().get("/admin/tests/changelistitem/")
    req.user = type("U", (), {"pk": 1})()
    admin_inst.cache_backend.set(
        admin_inst._changelist_cache_key(req),
        json.dumps(sample).encode("utf-8"),
        300,
    )

    # API returns different data — proves cache was NOT used
    fresh = [{"id": 99, "name": "fresh"}]
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = json.dumps(fresh).encode("utf-8")

    with patch("django_api_factory.admin.requests.get", return_value=fake_response):
        mymodels_qs, _ = admin_inst.get_api_data(req)
    items = list(mymodels_qs)
    assert items[0].name == "fresh"
