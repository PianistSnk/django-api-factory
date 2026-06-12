"""Tests for MyQuerySet (queryset.py) — in-memory cache across admin ops.

MyQuerySet keeps an in-memory `_result_cache` alive across Django admin's
chained operations (order_by, distinct, select_related, etc.) so that
APIAdmin's fake model instances can be iterated and sliced without going
to SQL. `__len__` and `__getitem__` return the actual cache size and
slice; they do NOT pretend to have more rows than are in memory.
"""

import pytest
from unittest.mock import MagicMock, patch

from django.db.models import QuerySet

from django_api_factory.queryset import MyQuerySet


def _make_qs(*, cache=None):
    """Build a MyQuerySet without running QuerySet.__init__.

    Stock QuerySet.__init__ wants a model class; we just want to test
    _result_cache handling, so skip init and set attrs by hand.

    cache=None means "no cache has been populated yet" — we still set
    _result_cache to None so MyQuerySet's `if self._result_cache is not None`
    check doesn't AttributeError before reaching the super() branch.
    """
    qs = MyQuerySet.__new__(MyQuerySet)
    qs._result_cache = cache
    return qs


# --- __getstate__ ---------------------------------------------------------

def test_getstate_returns_dict_copy():
    """__getstate__ overrides Django's default to avoid _fetch_all() on pickle."""
    qs = _make_qs(cache=[1, 2, 3])
    state = qs.__getstate__()
    # State is a shallow copy of __dict__ — the dict itself is new,
    # but its values (like the cache list) are still references.
    assert state is not qs.__dict__
    assert state["_result_cache"] == [1, 2, 3]


# --- _clone ---------------------------------------------------------------

def test_clone_copies_state_and_does_not_trigger_fetch_all():
    """_clone uses our __getstate__ so it never runs _fetch_all()."""
    qs = _make_qs(cache=[1, 2, 3])
    # Patch the parent _fetch_all to fail the test if it's called
    with patch.object(QuerySet, "_fetch_all", side_effect=AssertionError(
            "_fetch_all should NOT be called during MyQuerySet._clone()"
    )):
        new = qs._clone()
    assert new is not qs
    assert new._result_cache == [1, 2, 3]


def test_clone_with_no_cache():
    qs = _make_qs()  # no _result_cache
    new = qs._clone()
    # __getstate__ returns self.__dict__.copy() — _result_cache not set yet
    assert not hasattr(new, "_result_cache") or new._result_cache is None


# --- __len__ --------------------------------------------------------------

def test_len_with_cache_returns_cache_length():
    qs = _make_qs(cache=[10, 20, 30, 40])
    assert len(qs) == 4


def test_len_with_empty_cache_returns_zero():
    qs = _make_qs(cache=[])
    assert len(qs) == 0


def test_len_without_cache_falls_through_to_super():
    qs = _make_qs()  # no _result_cache
    with patch.object(QuerySet, "__len__", return_value=42) as mock_super:
        assert len(qs) == 42
    mock_super.assert_called_once()


# --- __getitem__ ----------------------------------------------------------

def test_getitem_int_returns_cache_item():
    qs = _make_qs(cache=["a", "b", "c"])
    assert qs[0] == "a"
    assert qs[1] == "b"
    assert qs[-1] == "c"


def test_getitem_slice_returns_cloned_queryset_with_slice():
    """A slice returns a new MyQuerySet with the sliced cache (cache kept
    alive across admin's chain of slice operations)."""
    qs = _make_qs(cache=[10, 20, 30, 40, 50])
    sliced = qs[1:4]
    assert isinstance(sliced, MyQuerySet)
    assert sliced._result_cache == [20, 30, 40]
    # The original cache is untouched
    assert qs._result_cache == [10, 20, 30, 40, 50]


def test_getitem_without_cache_falls_through_to_super():
    """When _result_cache is None, delegate to the parent (Django stock)."""
    qs = _make_qs()  # no _result_cache
    with patch.object(QuerySet, "__getitem__", return_value="from-super") as mock_super:
        assert qs[2] == "from-super"
    mock_super.assert_called_once_with(2)


# --- count ---------------------------------------------------------------

def test_count_with_cache_returns_cache_length():
    qs = _make_qs(cache=[1, 2, 3, 4, 5])
    assert qs.count() == 5


def test_count_without_cache_falls_through_to_super():
    qs = _make_qs()
    with patch.object(QuerySet, "count", return_value=999) as mock_super:
        assert qs.count() == 999
    mock_super.assert_called_once()


# --- order_by / distinct / select_related — cache-preserving no-ops -----

@pytest.mark.parametrize("method_name", ["order_by", "distinct", "select_related"])
def test_cache_preserving_method_returns_cloned_queryset_with_same_cache(method_name):
    """All three of order_by/distinct/select_related preserve _result_cache
    by _clone()ing and re-assigning the same cache list (no copy, no SQL).

    Why no re-sort inside order_by: see the long docstring in queryset.py —
    APIAdmin.get_api_data already does the right sort using its `convert()`
    coercion logic; re-sorting here on Django admin's lossy interpretation
    of `?o=` would clobber the user-driven sort.
    """
    cache = [3, 1, 4, 1, 5, 9, 2, 6]
    qs = _make_qs(cache=cache)
    method = getattr(qs, method_name)
    result = method()
    # Returned object is a new MyQuerySet (not the original)
    assert result is not qs
    assert isinstance(result, MyQuerySet)
    # Cache is preserved verbatim (same list, not a copy — the docstring
    # explicitly says "preserve `_result_cache` verbatim")
    assert result._result_cache is cache
    # Original cache is untouched
    assert qs._result_cache is cache



# --- ordered=True flag (Jun 2026 UnorderedObjectListWarning fix) -------


def test_myqueryset_reports_ordered_true():
    """MyQuerySet.ordered must be True so Django Paginator's
    `UnorderedObjectListWarning` doesn't fire on every changelist
    render. False positive: APIAdmin.get_api_data already sorts
    the cache (id-asc by default; user-driven ?o= parsed separately),
    so the cache IS ordered — we just need to tell Paginator.

    Regression test: if someone removes the `ordered = True` class
    attr from MyQuerySet, this test fails before any user hits the
    warning in production.
    """
    from django_api_factory.queryset import MyQuerySet
    assert MyQuerySet.ordered is True


def test_myqueryset_ordered_true_silences_paginator_warning():
    """End-to-end: paginating a MyQuerySet (with a populated
    `_result_cache`) must NOT raise UnorderedObjectListWarning,
    even when the cache is plain dicts (no implicit ordering)."""
    import warnings
    from django.core.paginator import Paginator, UnorderedObjectListWarning
    from django_api_factory.queryset import MyQuerySet

    # Build a MyQuerySet with a cache that has no natural ordering
    # (just dicts in insertion order — could be anything from the API)
    qs = MyQuerySet.__new__(MyQuerySet)
    qs._result_cache = [{"id": 3}, {"id": 1}, {"id": 2}]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UnorderedObjectListWarning)
        p = Paginator(qs, 1)
        _ = p.count
        _ = p.num_pages
    # None of the captured warnings should be UnorderedObjectListWarning
    bad = [w for w in caught if issubclass(w.category, UnorderedObjectListWarning)]
    assert bad == [], f"got {len(bad)} UnorderedObjectListWarning(s): {[str(w.message) for w in bad]}"
