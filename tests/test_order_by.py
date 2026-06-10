"""Tests for MyQuerySet.order_by preserving the cache.

NOTE: `MyQuerySet.order_by` is intentionally a no-op. The single source of
truth for sort order is `APIAdmin.get_api_data`, which parses `?o=` and
sorts the cache using our `convert()` logic. Django admin's ChangeList
also calls `order_by(...)` with a *different* parse of the same URL, and
re-sorting here would clobber the user-driven sort. See queryset.py for
the full rationale.
"""

import pytest
from unittest.mock import MagicMock
from django.db.models import F, OrderBy

from django_api_factory.models import APIModel
from django_api_factory.queryset import MyQuerySet


class OrderItem(APIModel):
    app_label = "tests"

    @classmethod
    def urls(cls, **kwargs):
        return "https://example.com"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta:
        app_label = "tests"


def _make_qs(rows):
    """Build a MyQuerySet with N fake mymodels that have id, name attrs."""
    qs = MyQuerySet(model=OrderItem)
    cache = []
    for r in rows:
        m = OrderItem()
        setattr(m, 'id', r["id"])
        setattr(m, 'pk', r["id"])
        setattr(m, 'name', r["name"])
        cache.append(m)
    qs._result_cache = cache
    return qs


# --- No-op contract: cache is preserved, not re-sorted ----------------

def test_order_by_preserves_cache_for_string():
    """qs.order_by('id') — does NOT re-sort. Cache is the source of truth."""
    qs = _make_qs([{"id": 3, "name": "c"}, {"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    result = qs.order_by("id")
    # Original order preserved, NOT [1, 2, 3].
    assert [m.id for m in result._result_cache] == [3, 1, 2]


def test_order_by_preserves_cache_for_negated_string():
    """qs.order_by('-id') — also no-op."""
    qs = _make_qs([{"id": 1, "name": "a"}, {"id": 3, "name": "c"}, {"id": 2, "name": "b"}])
    result = qs.order_by("-id")
    assert [m.id for m in result._result_cache] == [1, 3, 2]


def test_order_by_preserves_cache_for_F_expression():
    """qs.order_by(F('id')) — no-op, even with F() / OrderBy() args."""
    qs = _make_qs([{"id": 2, "name": "b"}, {"id": 1, "name": "a"}, {"id": 3, "name": "c"}])
    result = qs.order_by(F("id"))
    assert [m.id for m in result._result_cache] == [2, 1, 3]


def test_order_by_preserves_cache_for_OrderBy_descending():
    """qs.order_by(OrderBy(F('id'), descending=True)) — no-op."""
    qs = _make_qs([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
    result = qs.order_by(OrderBy(F("id"), descending=True))
    assert [m.id for m in result._result_cache] == [1, 2]


# --- Edge cases -------------------------------------------------------

def test_order_by_handles_missing_field():
    """qs.order_by('nonexistent_field') — no-op, no crash."""
    qs = _make_qs([{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    result = qs.order_by("nonexistent_field")
    assert [m.id for m in result._result_cache] == [2, 1]


def test_order_by_handles_no_args():
    """qs.order_by() with no args — just clone, cache preserved."""
    qs = _make_qs([{"id": 2, "name": "b"}, {"id": 1, "name": "a"}])
    result = qs.order_by()
    assert [m.id for m in result._result_cache] == [2, 1]


def test_order_by_handles_empty_cache():
    """qs.order_by('id') on an empty cache returns empty clone."""
    qs = MyQuerySet(model=OrderItem)
    qs._result_cache = []
    result = qs.order_by("id")
    assert result._result_cache == []


def test_order_by_handles_none_cache():
    """qs.order_by('id') when _result_cache is None — clone with None cache."""
    qs = MyQuerySet(model=OrderItem)
    qs._result_cache = None
    result = qs.order_by("id")
    assert result._result_cache is None


def test_order_by_returns_clone_not_self():
    """qs.order_by(...) returns a new MyQuerySet, not the same instance."""
    qs = _make_qs([{"id": 1, "name": "a"}])
    result = qs.order_by("id")
    assert result is not qs
    # But they share the cache (no re-sort would have produced a different list).
    assert result._result_cache is qs._result_cache
