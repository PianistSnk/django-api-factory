from django.db.models import QuerySet
import copy


class MyQuerySet(QuerySet):
    """
    A QuerySet that keeps an in-memory `_result_cache` alive across Django
    admin's chained operations (order_by, distinct, select_related, etc.).

    Why: APIAdmin creates fake model instances in memory. We need Django
    admin to iterate and slice them like a real queryset without going to
    SQL.

    The `__len__` and `__getitem__` overrides return the actual cache size
    and the actual cache slice — they do NOT pretend to have more rows
    than are in memory. The "total row count" (for the paginator) is
    handled separately by APIAdmin.get_paginator, which returns a custom
    Paginator subclass that knows the total via a class attribute.
    """

    def __getstate__(self):
        """Override Django's default __getstate__ which calls `_fetch_all()`
        on the queryset, triggering an unwanted SQL roundtrip when we
        only want a shallow copy. Return the instance's __dict__ directly.
        """
        return self.__dict__.copy()

    def _clone(self):
        # Use __getstate__ (which we override) instead of copy.copy so
        # we don't trigger _fetch_all on the parent QuerySet.
        new = self.__class__.__new__(self.__class__)
        new.__dict__.update(self.__getstate__())
        return new

    def __len__(self):
        # Just return the actual size of the cache. We do NOT pretend
        # to be a 100-row queryset when the cache only has 10.
        if self._result_cache is not None:
            return len(self._result_cache)
        return super().__len__()

    def __getitem__(self, k):
        # When admin paginates, it does qs[start:end]. Serve that from
        # the cache so we never run SQL.
        if self._result_cache is None:
            return super().__getitem__(k)
        if isinstance(k, slice):
            new = self._clone()
            new._result_cache = list(self._result_cache[k])
            return new
        return self._result_cache[k]

    def count(self):
        # Override `count()` to return cache size (used by some admin paths).
        if self._result_cache is not None:
            return len(self._result_cache)
        return super().count()

    # Keep the cache alive across chained operations
    def order_by(self, *args):
        """
        No-op: preserve `_result_cache` verbatim. The single source of
        truth for sort order is `APIAdmin.get_api_data` — it parses the
        `?o=` URL param (multi-col like `?o=-1.-3.4`) using our
        `convert()` logic for proper date/number coercion, and sorts the
        cache accordingly.

        Why no re-sort here: Django admin's `ChangeList.get_queryset`
        also calls `order_by(...)` with a DIFFERENT parse of the same
        `?o=` (it skips `__str__` because there's no `admin_order_field`,
        it appends `'-pk'` for deterministic ordering, and it only honors
        the FIRST field). If we re-sorted on ChangeList's args, we'd
        clobber the user-driven sort with ChangeList's lossy
        re-interpretation — and for multi-col with mixed directions,
        the result is dominated by whatever first arg ChangeList kept
        (usually NOT what the user asked for).

        Direct callers (tests, scripts) who need to sort should do so on
        `qs._result_cache` directly — `get_api_data` is the admin path.
        """
        new = self._clone()
        new._result_cache = self._result_cache
        return new

    def distinct(self, *args):
        new = self._clone()
        new._result_cache = self._result_cache
        return new

    def select_related(self, *args):
        new = self._clone()
        new._result_cache = self._result_cache
        return new
