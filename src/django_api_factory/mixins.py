"""
Mixins for APIAdmin.

Each mixin is no-op by default (or generic) so subclasses can opt in by
overriding hooks. Keeps the core library free of project-specific assumptions.
"""

from __future__ import annotations

import datetime
from io import BytesIO
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from django.contrib.admin.models import LogEntry


class AuditLogMixin:
    """
    Hooks for query / download audit logging.

    Default behavior: no-op (does nothing). Project-specific callers can subclass
    and override these methods to write to django.contrib.admin.models.LogEntry
    or any other audit backend.

    To use, mix into your APIAdmin subclass:

        class PostAdmin(AuditLogMixin, APIAdmin):
            def log_query(self, request, model_name):
                LogEntry.objects.create(
                    action_time=datetime.datetime.now(),
                    user=request.user,
                    action_flag=4,  # custom query flag
                    content_type=ContentType.objects.get(model=model_name),
                )

            def log_download(self, request, model_name, filename, type_):
                LogEntry.objects.create(
                    action_time=datetime.datetime.now(),
                    user=request.user,
                    action_flag=6,  # custom download flag
                    object_repr=f"{filename}.{type_}",
                    content_type=ContentType.objects.get(model=model_name),
                )
    """

    #: Set to True to enable default LogEntry writes using custom flags.
    #: If False (default), no audit is written.
    enable_audit_log: bool = False

    def log_query(self, request, model_name: str) -> Optional["LogEntry"]:
        """
        Called once per changelist data load.
        Default: no-op. Override to record query audit.
        """
        return None

    def log_download(
        self,
        request,
        model_name: str,
        filename: str,
        type_: str,
    ) -> Optional["LogEntry"]:
        """
        Called when your custom view proxies a file download from the
        external API. (Note: this library used to ship a `view_or_download`
        helper, but it was removed in M1 — implement the proxy in your
        own project and call `self.log_download(...)` there.)
        Default: no-op. Override to record download audit.
        """
        return None


class ExportMixin:
    """
    Add an `export_to_excel` action to your admin.

    Usage:

        class PostAdmin(APIAdmin, ExportMixin):
            actions = ["export_to_excel_action"]

            @admin.action(description="Export to Excel")
            def export_to_excel_action(self, request, queryset):
                return self.export_to_excel(request, queryset)

    By default, exports every column in `self.export_list` (set by APIAdmin
    on changelist load). Override `get_export_fields` or `get_export_data`
    to customize.
    """

    def get_export_fields(self):
        """Return the list of field names to export. Default: `self.export_list`."""
        return getattr(self, "export_list", None)

    def get_export_data(self, queryset):
        """Return a list of dicts (one per row) for the export."""
        fields = self.get_export_fields() or []
        return [{field: getattr(obj, field, "") for field in fields} for obj in queryset]

    def export_to_excel(self, request, queryset):
        """Build an .xlsx response from `queryset` using openpyxl."""
        try:
            from openpyxl import Workbook
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "ExportMixin requires openpyxl: `pip install openpyxl`"
            ) from exc

        wb = Workbook()
        ws = wb.active
        ws.title = "Data Export"

        headers = self.get_export_fields() or []
        ws.append(list(headers))
        for row in self.get_export_data(queryset):
            ws.append([row.get(h, "") for h in headers])

        model_name = self.model._meta.verbose_name
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        filename = f"{model_name}_{date_str}.xlsx"

        virtual_workbook = BytesIO()
        wb.save(virtual_workbook)
        virtual_workbook.seek(0)
        response = HttpResponse(
            virtual_workbook.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment;filename="{filename}"'
        return response


# Re-export to preserve the historical `from .admin import quote` import in
# the original code. New code should `from urllib.parse import quote` directly.
from urllib.parse import quote  # noqa: E402,F401

import json
import logging
from django.http import HttpResponse, JsonResponse
from django.urls import path
from typing import Optional

logger = logging.getLogger(__name__)


# --- Schema registry (T1.3 + T1.4 — register fields once, lock-safe) -----

import threading as _threading


class SchemaRegistry:
    """
    Track which fields have already been registered on which model classes.

    Solves two problems simultaneously:
    1. (T1.3) Avoid re-running `model.add_to_class(...)` for every request —
       the field list is registered **once** per model+fields combo.
    2. (T1.4) Make concurrent registration safe across threads / workers —
       a module-level `threading.Lock` serializes `add_to_class` calls.

    Usage (from APIAdmin.get_api_data)::

        from django_api_factory.mixins import schema_registry

        # `fields` is the list of field names returned by the API.
        schema_registry.register(self.model, fields)

    Subclasses can subclass to add field-type customisation (e.g. pick
    `IntegerField` vs `CharField` based on the first row's values).
    """

    def __init__(self):
        # {model_class: set(registered_field_names)}
        self._registry: dict = {}
        # Serializes add_to_class across threads (intra-process).
        # For multi-process (gunicorn workers), Django's model class
        # registry is per-process anyway, so each worker builds its own.
        self._lock = _threading.Lock()

    def register(self, model, fields):
        """
        Register `fields` on `model`. Idempotent — only fields not already
        registered are added; the rest are skipped.

        Returns the list of fields that were *actually* added (for logging
        or test assertions).
        """
        with self._lock:
            registered = self._registry.setdefault(model, set())
            to_add = [f for f in fields if f not in registered]
            if to_add:
                from django.db import models as dj_models
                for f in to_add:
                    model.add_to_class(f, dj_models.CharField(max_length=255))
                    registered.add(f)
            return to_add

    def is_registered(self, model, field) -> bool:
        """True if `field` was previously registered on `model`."""
        return field in self._registry.get(model, set())

    def registered_fields(self, model) -> list:
        """All fields registered on `model` (in insertion order)."""
        return list(self._registry.get(model, set()))

    def reset(self):
        """Drop all registrations. Used by tests."""
        with self._lock:
            self._registry.clear()


# Module-level singleton — shared across all APIAdmin instances.
schema_registry = SchemaRegistry()


# --- Cache backend abstraction (T1.2 Redis-decoupling) -------------------

class BaseCacheBackend:
    """
    Pluggable cache backend for APIAdmin.

    Subclass and set `APIAdmin.cache_backend_class` to swap the default
    NullCacheBackend for Redis, memcached, Django cache, or your own
    implementation. Core does not import any specific client library
    (redis-py, pymemcache, etc.) — subclasses do.

    The default backend (`NullCacheBackend`) is a no-op, so the library
    works out-of-the-box without any cache configuration.
    """

    def get(self, key: str) -> Optional[bytes]:
        """Return the cached bytes for `key`, or None on miss / error."""
        raise NotImplementedError

    def set(self, key: str, value: bytes, ttl: int) -> None:
        """Store `value` under `key` for `ttl` seconds. No-op on error."""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """Remove `key`. No-op if missing or on error."""
        raise NotImplementedError


class NullCacheBackend(BaseCacheBackend):
    """No-op cache. Default. Use this when caching isn't needed."""

    def get(self, key: str) -> Optional[bytes]:
        return None

    def set(self, key: str, value: bytes, ttl: int) -> None:
        pass

    def delete(self, key: str) -> None:
        pass


class RedisCacheBackend(BaseCacheBackend):
    """
    Redis backend using the `redis-py` client.

    Importing this class does NOT require redis-py to be installed —
    the import is deferred to `__init__` so core stays light.

    Connection settings: if no args given, reads from
    `django.conf.settings.REDIS_HOST/PORT/DB/PWD`. Otherwise explicit
    args are used.

        # default: from settings
        backend = RedisCacheBackend()

        # explicit
        backend = RedisCacheBackend(host="...", port=6379, db=0)

    Any connection / IO error is swallowed and treated as a cache miss.

    Opt-in only: the library does NOT auto-pick this backend. To use it,
    set `cache_backend_class = RedisCacheBackend` on your admin class.
    """

    def __init__(self, host: str = None, port: int = None,
                 db: int = None, password=None, socket_connect_timeout: int = 2):
        try:
            import redis  # noqa: delayed import — keeps core redis-free
        except ImportError as exc:
            raise ImportError(
                "RedisCacheBackend requires redis-py: `pip install redis`"
            ) from exc
        # Pull from Django settings when args are omitted
        from django.conf import settings
        if host is None:
            host = getattr(settings, "REDIS_HOST", "127.0.0.1")
        if port is None:
            port = getattr(settings, "REDIS_PORT", 6379)
        if db is None:
            db = getattr(settings, "REDIS_DB", 0)
        if password is None:
            password = getattr(settings, "REDIS_PWD", None)
        self._client = redis.Redis(
            host=host, port=port, db=db, password=password,
            socket_connect_timeout=socket_connect_timeout,
        )

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self._client.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis cache get failed: %s", exc)
            return None

    def set(self, key: str, value: bytes, ttl: int) -> None:
        try:
            self._client.set(key, value, ex=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis cache set failed: %s", exc)

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis cache delete failed: %s", exc)


class ActionFormMixin:
    """
    Add modal-form + ajax-submit capability to admin actions, with no
    dependency on simpleui (or any other admin theme).

    Usage::

        class MyAdmin(ActionFormMixin, APIAdmin):
            actions = ['add_remarks']

            @admin.action(description="Add remarks")
            def add_remarks(self, request, queryset):
                remarks = request.POST.get("remarks", "")
                # ... do work
            add_remarks.layer = {
                "params": [
                    {"type": "input", "key": "remarks", "label": "备注", "require": False},
                ]
            }

    The front-end (see templates/admin/action_form_modal.html) auto-discovers
    actions with a `.layer` attribute, opens a modal with the declared form
    fields, and POSTs the form back to the action-submit endpoint.

    Subclasses can override:
    - `action_form_view` / `action_submit_view` to customize the protocol
    - The default template via `action_form_template` class attr
    """

    #: Path to the JS+modal template that powers the action form UI.
    #: Subclasses can override (e.g. to a project-specific template).
    action_form_template: str = "admin/django_api_factory/action_form_modal.html"

    def get_urls(self):
        urls = super().get_urls()
        info = (self.model._meta.app_label, self.model._meta.model_name)
        custom = [
            path(
                "action-form/<str:action_name>/",
                self.admin_site.admin_view(self.action_form_view),
                name="%s_%s_action_form" % info,
            ),
            path(
                "action-submit/<str:action_name>/",
                self.admin_site.admin_view(self.action_submit_view),
                name="%s_%s_action_submit" % info,
            ),
        ]
        return custom + urls

    def _resolve_action(self, action_name):
        """Return (callable, short_name, description) or raise Http404."""
        if not hasattr(self, action_name):
            return None
        func, action, description = self.get_action(action_name)
        if func is None:
            return None
        return func, action, description

    def action_form_view(self, request, action_name):
        """
        GET endpoint. Returns the action's form schema (the `.layer` attr) as
        JSON: `{"title": <description>, "params": [<field>, ...]}`.

        If the action has no `.layer`, returns `{"params": []}` (the front-end
        will just call the action without showing a form).
        """
        resolved = self._resolve_action(action_name)
        if resolved is None:
            return JsonResponse(
                {"status": "error", "msg": f"action {action_name!r} not found"},
                status=404,
            )
        func, _action, description = resolved
        layer = getattr(func, "layer", None) or {}
        params = layer.get("params", []) if isinstance(layer, dict) else []
        title = layer.get("title", description) if isinstance(layer, dict) else description
        # simpleui-style layer extras (T1.5 simpleui compatibility):
        # - width: any CSS value (e.g. "40%", "500px") for the modal width
        # - icon, type, style: cosmetic on the action button itself
        width = layer.get("width") if isinstance(layer, dict) else None
        icon = getattr(func, "icon", None)
        css_type = getattr(func, "type", None)  # 'type' is a Python builtin name
        style = getattr(func, "style", None)
        return JsonResponse({
            "title": title,
            "params": params,
            "action_name": action_name,
            "width": width,
            "icon": icon,
            "type": css_type,
            "style": style,
        })

    def action_submit_view(self, request, action_name):
        """
        POST endpoint. Executes the action with form data in request.POST.

        Body params:
        - `_selected` — comma-separated list of selected row IDs (matches the
          standard Django admin action checkbox protocol)
        - `select_across` — "0" (selected only) or "1" (all rows on page)
        - Any custom fields declared in `.layer` (e.g. `remarks`, `status`)

        Returns JSON: `{"status": "success|error|redirect", "msg": ..., "url": ...}`
        For actions that return an HttpResponse (e.g. a file download), the
        response is passed through unchanged.
        """
        if request.method != "POST":
            return JsonResponse(
                {"status": "error", "msg": "POST required"}, status=405
            )
        resolved = self._resolve_action(action_name)
        if resolved is None:
            return JsonResponse(
                {"status": "error", "msg": f"action {action_name!r} not found"},
                status=404,
            )
        func, _action, description = resolved

        # Build queryset from selection
        try:
            cl = self.get_changelist_instance(request)
            qs = cl.get_queryset(request)
        except Exception:  # noqa: BLE001
            qs = self.get_queryset(request)

        selected = request.POST.get("_selected", "")
        select_across = request.POST.get("select_across", "0")
        if select_across == "0" and selected:
            ids = [int(x) for x in selected.split(",") if x.strip().isdigit()]
            qs = qs.filter(pk__in=ids)

        # Run the action
        try:
            result = func(self, request, qs)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Action %s failed", action_name)
            return JsonResponse({"status": "error", "msg": str(exc)}, status=500)

        # Normalize return -> JSON
        if result is None:
            return JsonResponse({"status": "success", "msg": "Success!"})
        if isinstance(result, HttpResponse):
            return result  # file download / redirect etc.
        if isinstance(result, dict):
            return JsonResponse(result)
        return JsonResponse({"status": "success", "msg": str(result)})

