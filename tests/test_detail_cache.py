"""Tests for detail-view cache (T1.5) + page-iteration (M2)."""

import json
import pytest
from unittest.mock import MagicMock, patch
from django.core.exceptions import ObjectDoesNotExist

from django_api_factory.admin import APIAdmin
from django_api_factory.models import APIModel
from django_api_factory.mixins import BaseCacheBackend, NullCacheBackend, schema_registry


# --- Test fixtures --------------------------------------------------------

class Item(APIModel):
    app_label = "tests"

    @classmethod
    def urls(cls, page=1, page_size=10, **kwargs):
        return f"https://example.com/items?_page={page}&_limit={page_size}"

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
def item_admin():
    inst = APIAdmin.__new__(APIAdmin)
    inst.model = Item
    if hasattr(inst, "_cache_backend_inst"):
        del inst._cache_backend_inst
    inst._cache_backend_inst = InMemoryCacheBackend()
    inst.cache_backend_class = NullCacheBackend if False else InMemoryCacheBackend
    inst.changelist_cache_enabled = False
    inst.changelist_cache_ttl = 0
    inst.detail_cache_enabled = False
    inst.detail_cache_ttl = 300
    inst.cache_ttl = 300
    inst.request_timeout = 10
    inst.paras_list = ["q", "o", "dt", "p"]
    inst.date_params = []
    inst.multi_value_separator = "\u3001"
    inst.list_per_page = 10
    inst.search_fields = []
    inst.actions = []
    inst.expected_total = 0
    fake_qs = MagicMock()
    fake_qs.model = Item
    fake_qs.get.side_effect = Item.DoesNotExist()
    inst.get_queryset = lambda req: fake_qs
    schema_registry.reset()
    return inst


# --- _detail_cache_key --------------------------------------------------

def test_detail_cache_key_differs_from_detail(item_admin):
    from django.test import RequestFactory
    req = RequestFactory().get("/admin/tests/item/?q=foo")
    req.user = type("U", (), {"pk": 1})()
    detail_key = item_admin._detail_cache_key(req)
    from django_api_factory.admin import APIAdmin
    inst2 = APIAdmin.__new__(APIAdmin)
    inst2.model = Item
    inst2.list_per_page = 10
    inst2.expected_total = 0
    inst2.cache_backend_class = InMemoryCacheBackend
    inst2._cache_backend_inst = InMemoryCacheBackend()
    from django.test import RequestFactory
    req2 = RequestFactory().get("/admin/tests/item/?q=foo")
    req2.user = type("U", (), {"pk": 1})()
    changelist_key = inst2._changelist_cache_key(req2)
    assert "detail:" in detail_key
    assert "changelist:" in changelist_key
    assert detail_key != changelist_key


def test_detail_cache_key_scopes_by_user_and_model(item_admin):
    from django.test import RequestFactory
    req_a = RequestFactory().get("/admin/tests/item/")
    req_a.user = type("U", (), {"pk": 1})()
    req_b = RequestFactory().get("/admin/tests/item/")
    req_b.user = type("U", (), {"pk": 2})()
    assert item_admin._detail_cache_key(req_a) != item_admin._detail_cache_key(req_b)


# --- get_object: cache hit (T1.5) ---------------------------------------

def test_get_object_uses_cache_when_present(item_admin):
    from django.test import RequestFactory
    request = RequestFactory().get("/admin/tests/item/")
    request.user = type("U", (), {"pk": 1})()
    items = [
        {"id": 1, "name": "first"},
        {"id": 2, "name": "second"},
    ]
    item_admin.detail_cache_enabled = True
    item_admin.cache_backend.set(
        item_admin._detail_cache_key(request),
        json.dumps(items).encode("utf-8"),
        300,
    )
    obj = item_admin.get_object(request, 2)
    assert obj is not None
    assert obj.id == 2
    assert obj.name == "second"


# --- get_object: page-iteration fallback (M2 server-side pagination) -----

def test_get_object_finds_id_by_iterating_pages(monkeypatch, item_admin):
    """When id is not in cache, iterate pages until found."""
    from django.test import RequestFactory
    from unittest.mock import patch

    item_admin.expected_total = 30  # 3 pages of 10

    # get_api_data will be called once per page. Page 1 returns ids 1-10,
    # page 2 returns 11-20, page 3 returns 21-30.
    def fake_get_api_data(request, *args, **kwargs):
        from django_api_factory.queryset import MyQuerySet
        page = int(request.GET.get("p", 1))
        items = [
            {"id": (page - 1) * 10 + i + 1, "name": f"item_{page}_{i}"}
            for i in range(10)
        ]
        m = MyQuerySet(model=Item)
        m._result_cache = [Item(id=it["id"], pk=it["id"], name=it["name"]) for it in items]
        return m, ["id", "name"]

    with patch.object(APIAdmin, "get_api_data", side_effect=fake_get_api_data):
        request = RequestFactory().get("/admin/tests/item/15/")
        request.user = type("U", (), {"pk": 1})()
        obj = item_admin.get_object(request, 15)

    assert obj is not None
    assert obj.id == 15
    assert obj.name == "item_2_4"  # 15 = (2-1)*10 + 5 -> 0-indexed 4


def test_get_object_returns_none_when_id_not_on_any_page(monkeypatch, item_admin):
    """If id is not in any fetched page, return None (don't crash).

    The fast-path direct page lookup is uncapped (a real-world admin
    may underestimate `expected_total` — better to find the row than
    404). The slow path is also bounded. We test the case where the
    API simply doesn't have the id at all."""
    from django.test import RequestFactory
    from django_api_factory.queryset import MyQuerySet

    item_admin.expected_total = 30

    def fake_get_api_data(request, *args, **kwargs):
        page = int(request.GET.get("p", 1))
        # All pages return 10 rows of ids (page-1)*10+1..page*10,
        # capped at 3 pages worth. id=999 falls past page 100 = ids
        # 991-1000, but page 100 returns []. So fast path on page 100
        # yields empty, slow path on pages 1..3 yields nothing, → None.
        if page > 3:
            items = []
        else:
            items = [{"id": (page - 1) * 10 + i + 1, "name": "x"} for i in range(10)]
        m = MyQuerySet(model=Item)
        m._result_cache = []
        for it in items:
            obj = Item(id=it["id"], pk=it["id"])
            obj.name = it["name"]
            m._result_cache.append(obj)
        return m, ["id", "name"]

    with patch.object(APIAdmin, "get_api_data", side_effect=fake_get_api_data):
        request = RequestFactory().get("/admin/tests/item/999/")
        request.user = type("U", (), {"pk": 1})()
        obj = item_admin.get_object(request, 999)
    assert obj is None


def test_get_object_stops_iterating_when_page_returns_short(monkeypatch, item_admin):
    """If the API's default order doesn't put id in its computed
    target_page (e.g. backend sorts by name, not id), the fast-path
    direct lookup fails and we fall back to page iteration, which
    stops early when a page returns fewer rows than page_size.

    To force slow-path exercise, leave `expected_total=0` (fixture
    default) so slow path's max_pages cap is 1 — fast path then fails
    on page 2 (the computed target_page), and slow path walks page 1
    (where id=12 lives) and finds it. Total 2 calls.
    """
    from django.test import RequestFactory
    from django_api_factory.queryset import MyQuerySet

    # NOTE: do NOT set expected_total — leave it at 0 so slow-path
    # max_pages is 1 (only walks page 1, where id=12 lives).
    # The fast path will still call page 2 (target_page=2) and fail
    # there, but that's 1 call; the slow path then walks page 1 and
    # finds id=12. Total 2 calls.

    call_count = [0]

    def fake_get_api_data(request, *args, **kwargs):
        call_count[0] += 1
        page = int(request.GET.get("p", 1))
        if page == 1:
            # page 1: ids 100-109 (contains id=12? No — id=12 is BELOW 100)
            items = [{"id": i, "name": "x"} for i in range(100, 110)]
        elif page == 2:
            # page 2: ids 200-209 (NOT 11-20 — id=12 is nowhere here)
            items = [{"id": i, "name": "x"} for i in range(200, 210)]
        else:
            items = []  # 0 rows
        m = MyQuerySet(model=Item)
        m._result_cache = []
        for it in items:
            obj = Item(id=it["id"], pk=it["id"])
            obj.name = it["name"]
            m._result_cache.append(obj)
        return m, ["id", "name"]

    with patch.object(APIAdmin, "get_api_data", side_effect=fake_get_api_data):
        request = RequestFactory().get("/admin/tests/item/12/")
        request.user = type("U", (), {"pk": 1})()
        obj = item_admin.get_object(request, 12)
    # Fast path: target_page=2 → call page 2 (ids 200-209, no 12) → miss.
    # Slow path: max_pages=1 → call page 1 (ids 100-109, no 12) → miss.
    # Final result: not found, return None. 2 calls, no 12.
    assert obj is None
    assert call_count[0] == 2


# --- User isolation ------------------------------------------------------

def test_user_isolation_in_detail_cache(monkeypatch, item_admin):
    from django.test import RequestFactory
    from django_api_factory.queryset import MyQuerySet

    item_admin.detail_cache_enabled = True
    item_admin.expected_total = 5

    def fake_get_api_data(request, *args, **kwargs):
        m = MyQuerySet(model=Item)
        user_pk = request.user.pk
        m._result_cache = [Item(id=1, pk=1, name=f"user_{user_pk}")]
        return m, ["id", "name"]

    with patch.object(APIAdmin, "get_api_data", side_effect=fake_get_api_data):
        req_a = RequestFactory().get("/admin/tests/item/1/")
        req_a.user = type("U", (), {"pk": 1})()
        req_b = RequestFactory().get("/admin/tests/item/1/")
        req_b.user = type("U", (), {"pk": 2})()
        obj_a = item_admin.get_object(req_a, 1)
        obj_b = item_admin.get_object(req_b, 1)
    assert obj_a is not None and obj_a.name == "user_1"
    assert obj_b is not None and obj_b.name == "user_2"


# --- Build mymodel from item ---------------------------------------------

def test_build_mymodel_from_item_registers_fields_and_sets_values(item_admin):
    schema_registry.register(Item, ["name"])
    item = {"id": 42, "name": "Alice", "email": "alice@example.com"}
    obj = item_admin._build_mymodel_from_item(item)
    assert obj.id == 42
    assert obj.name == "Alice"
    assert schema_registry.is_registered(Item, "name")
