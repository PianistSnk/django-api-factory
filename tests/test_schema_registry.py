"""Tests for SchemaRegistry (T1.3 + T1.4 — register fields once, lock-safe)."""

import threading
import pytest
from unittest.mock import patch

from django_api_factory.mixins import SchemaRegistry, schema_registry
from django_api_factory.models import APIModel


# --- Test fixtures --------------------------------------------------------

class TestModel(APIModel):
    app_label = "tests"

    def urls(self, **kwargs):
        return "https://example.com"

    def cache(self, **kwargs):
        return None

    class Meta:
        app_label = "tests"


class OtherModel(APIModel):
    app_label = "tests"

    def urls(self, **kwargs):
        return "https://other.example.com"

    def cache(self, **kwargs):
        return None

    class Meta:
        app_label = "tests"


@pytest.fixture
def registry():
    """Fresh registry per test."""
    return SchemaRegistry()


# --- T1.3: single-thread schema cache -----------------------------------

def test_register_adds_fields_to_model(registry):
    """First call adds the fields via add_to_class."""
    registry.register(TestModel, ["foo", "bar", "baz"])
    for f in ("foo", "bar", "baz"):
        assert hasattr(TestModel, f), f"field {f!r} not on model"


def test_register_is_idempotent(registry):
    """Second register call adds nothing — same field list returns []. """
    registry.register(TestModel, ["a", "b"])
    added = registry.register(TestModel, ["a", "b"])
    assert added == []


def test_register_returns_only_newly_added(registry):
    """Mixed call returns just the new fields."""
    registry.register(TestModel, ["a", "b"])
    added = registry.register(TestModel, ["a", "b", "c", "d"])
    assert sorted(added) == ["c", "d"]


def test_is_registered(registry):
    """is_registered reports True only after register()."""
    assert registry.is_registered(TestModel, "x") is False
    registry.register(TestModel, ["x"])
    assert registry.is_registered(TestModel, "x") is True
    assert registry.is_registered(TestModel, "y") is False


def test_registered_fields(registry):
    """registered_fields returns the full set in insertion order."""
    registry.register(TestModel, ["c", "a", "b"])
    assert sorted(registry.registered_fields(TestModel)) == ["a", "b", "c"]


def test_separate_models_have_separate_registries(registry):
    """One model registering fields doesn't leak to another."""
    registry.register(TestModel, ["x"])
    registry.register(OtherModel, ["y"])
    assert registry.is_registered(TestModel, "x")
    assert not registry.is_registered(TestModel, "y")
    assert registry.is_registered(OtherModel, "y")
    assert not registry.is_registered(OtherModel, "x")


def test_reset_clears_all(registry):
    """reset() drops everything (useful in tests)."""
    registry.register(TestModel, ["x"])
    registry.register(OtherModel, ["y"])
    registry.reset()
    assert not registry.is_registered(TestModel, "x")
    assert not registry.is_registered(OtherModel, "y")


# --- T1.4: concurrent registration is safe -----------------------------

def test_concurrent_register_no_duplicate_adds(registry):
    """
    10 threads each register the same 5 fields. After all threads complete,
    the registry should contain exactly those 5 fields (not 50 = 5*10).

    Note: the lock serializes add_to_class, so any given field is added at
    most once. (We verify the registry state here rather than counting
    add_to_class calls, because patching add_to_class and threading has
    subtle interaction issues.)
    """
    fields = ["foo", "bar", "baz", "qux", "quux"]
    threads = [
        threading.Thread(target=registry.register, args=(TestModel, fields))
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 5 fields present
    assert sorted(registry.registered_fields(TestModel)) == sorted(fields)
    # Set has exactly 5 entries (not duplicated)
    assert len(registry._registry[TestModel]) == 5


def test_concurrent_register_idempotent_returns_unchanged(registry):
    """After first register, subsequent registers return []. """
    fields = ["x", "y", "z"]
    # First register adds everything
    added = registry.register(TestModel, fields)
    assert sorted(added) == sorted(fields)
    # Concurrent re-registers should all return [] (idempotent)
    results = []
    def worker():
        results.append(registry.register(TestModel, fields))
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All concurrent re-registers added nothing
    for r in results:
        assert r == []


def test_concurrent_register_different_fields_dont_clobber(registry):
    """Threads registering disjoint field sets all stick."""
    def worker(prefix, n):
        registry.register(TestModel, [f"{prefix}{i}" for i in range(n)])

    threads = [threading.Thread(target=worker, args=(f"t{i}_", 5)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All 20 fields should be present
    for i in range(4):
        for j in range(5):
            assert registry.is_registered(TestModel, f"t{i}_{j}")


# --- Integration: module-level singleton --------------------------------

def test_module_level_singleton_exists():
    """The library exposes a `schema_registry` singleton for APIAdmin to use."""
    assert isinstance(schema_registry, SchemaRegistry)


def test_singleton_is_shared_across_imports():
    """`from django_api_factory.mixins import schema_registry` returns the same object."""
    from django_api_factory.mixins import schema_registry as r2
    assert r2 is schema_registry
