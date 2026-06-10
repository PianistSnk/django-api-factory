"""Tests for cache backend abstraction (T1.2 Redis-decoupling)."""

import pytest
from unittest.mock import patch, MagicMock

from django_api_factory.mixins import (
    BaseCacheBackend,
    NullCacheBackend,
    RedisCacheBackend,
)


# --- BaseCacheBackend (abstract) -----------------------------------------

def test_base_cache_backend_raises_on_get():
    """Subclasses must implement get(); calling on the base raises."""
    backend = BaseCacheBackend()
    with pytest.raises(NotImplementedError):
        backend.get("k")

def test_base_cache_backend_raises_on_set():
    backend = BaseCacheBackend()
    with pytest.raises(NotImplementedError):
        backend.set("k", b"v", 60)

def test_base_cache_backend_raises_on_delete():
    backend = BaseCacheBackend()
    with pytest.raises(NotImplementedError):
        backend.delete("k")


# --- NullCacheBackend (default) ------------------------------------------

def test_null_backend_get_returns_none():
    """Default backend never returns cached data."""
    backend = NullCacheBackend()
    assert backend.get("any_key") is None

def test_null_backend_set_is_noop():
    """Default backend accepts writes but stores nothing."""
    backend = NullCacheBackend()
    backend.set("k", b"value", 300)  # must not raise
    assert backend.get("k") is None  # still no data

def test_null_backend_delete_is_noop():
    backend = NullCacheBackend()
    backend.delete("k")  # must not raise


# --- RedisCacheBackend (with mocked redis-py) ----------------------------

def test_redis_backend_uses_default_settings(monkeypatch):
    """RedisCacheBackend() with no args reads REDIS_HOST/PORT/DB/PWD from Django settings."""
    from django.conf import settings
    monkeypatch.setattr(settings, "REDIS_HOST", "redis.example.com", raising=False)
    monkeypatch.setattr(settings, "REDIS_PORT", 6380, raising=False)
    monkeypatch.setattr(settings, "REDIS_DB", 3, raising=False)
    monkeypatch.setattr(settings, "REDIS_PWD", "secret", raising=False)

    fake_redis_client = MagicMock()
    with patch("redis.Redis", return_value=fake_redis_client) as mock_redis:
        backend = RedisCacheBackend()  # no-arg = reads from settings
        # Verify redis.Redis was called with our settings
        mock_redis.assert_called_once_with(
            host="redis.example.com", port=6380, db=3, password="secret",
            socket_connect_timeout=2,
        )


def test_redis_backend_get_returns_bytes_or_none():
    """get() returns the raw bytes from redis, or None on miss."""
    fake_redis = MagicMock()
    fake_redis.get.return_value = b'{"key": "value"}'
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend(host="x", port=1)
        assert backend.get("mykey") == b'{"key": "value"}'
        fake_redis.get.assert_called_with("mykey")


def test_redis_backend_get_returns_none_on_miss():
    fake_redis = MagicMock()
    fake_redis.get.return_value = None
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        assert backend.get("missing") is None


def test_redis_backend_get_swallows_errors():
    """get() must never raise — connection errors become cache miss."""
    fake_redis = MagicMock()
    fake_redis.get.side_effect = ConnectionError("redis down")
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        assert backend.get("k") is None  # error swallowed


def test_redis_backend_set_calls_redis_set():
    fake_redis = MagicMock()
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        backend.set("mykey", b"myvalue", 300)
        fake_redis.set.assert_called_with("mykey", b"myvalue", ex=300)


def test_redis_backend_set_swallows_errors():
    fake_redis = MagicMock()
    fake_redis.set.side_effect = ConnectionError("redis down")
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        backend.set("k", b"v", 60)  # must not raise


def test_redis_backend_delete():
    fake_redis = MagicMock()
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        backend.delete("mykey")
        fake_redis.delete.assert_called_with("mykey")


def test_redis_backend_delete_swallows_errors():
    fake_redis = MagicMock()
    fake_redis.delete.side_effect = ConnectionError("redis down")
    with patch("redis.Redis", return_value=fake_redis):
        backend = RedisCacheBackend()
        backend.delete("k")  # must not raise


def test_redis_backend_raises_import_error_if_redis_missing(monkeypatch):
    """If redis-py isn't installed, importing the class is fine but __init__ raises."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("No module named 'redis'")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        with pytest.raises(ImportError, match="redis-py"):
            RedisCacheBackend()


# --- Integration: APIAdmin picks the right backend -----------------------

def test_apiadmin_default_backend_is_null():
    """Default = NullCacheBackend (no caching, no redis)."""
    from django_api_factory.admin import APIAdmin
    # Bypass ModelAdmin __init__ (which needs model + admin_site)
    admin = APIAdmin.__new__(APIAdmin)
    # Make sure no stray REDIS_HOST triggers any auto-pick
    if hasattr(admin, "_cache_backend_inst"):
        del admin._cache_backend_inst
    backend = admin.cache_backend
    assert isinstance(backend, NullCacheBackend)


def test_apiadmin_does_not_auto_pick_redis_even_with_redis_host(monkeypatch):
    """Even if REDIS_HOST is set, APIAdmin does NOT auto-pick RedisCacheBackend.
    Opt-in is intentional. Subclasses must set `cache_backend_class` explicitly.
    """
    from django.conf import settings
    from django_api_factory.admin import APIAdmin
    monkeypatch.setattr(settings, "REDIS_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(settings, "REDIS_PORT", 6379, raising=False)
    admin = APIAdmin.__new__(APIAdmin)
    if hasattr(admin, "_cache_backend_inst"):
        del admin._cache_backend_inst
    backend = admin.cache_backend
    assert isinstance(backend, NullCacheBackend), \
        "APIAdmin should not auto-pick RedisCacheBackend — opt-in only"


def test_apiadmin_opt_in_to_redis():
    """Setting `cache_backend_class = RedisCacheBackend` opts in to Redis."""
    from django_api_factory.admin import APIAdmin

    class RedisAdmin(APIAdmin):
        cache_backend_class = RedisCacheBackend

    admin = RedisAdmin.__new__(RedisAdmin)
    if hasattr(admin, "_cache_backend_inst"):
        del admin._cache_backend_inst
    fake_redis = MagicMock()
    with patch("redis.Redis", return_value=fake_redis):
        backend = admin.cache_backend
        assert isinstance(backend, RedisCacheBackend)


def test_apiadmin_respects_explicit_cache_backend_class():
    """If user sets cache_backend_class, that wins over auto-detection."""
    from django_api_factory.admin import APIAdmin

    class MyBackend(NullCacheBackend):
        pass

    class MyAdmin(APIAdmin):
        cache_backend_class = MyBackend

    admin = MyAdmin.__new__(MyAdmin)
    backend = admin.cache_backend
    assert isinstance(backend, MyBackend)
