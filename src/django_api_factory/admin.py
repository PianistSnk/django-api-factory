import datetime
import json
import locale
import logging
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.decorators import display
from django.contrib.auth import get_permission_codename
from django.utils.safestring import mark_safe

from django_api_factory.changelist import APIChangeList, APIADMIN_RESERVED_GET_PARAMS
from django_api_factory.filter import APIMultiSelectFilter
from django_api_factory.mixins import (
    ActionFormMixin,
    AuditLogMixin,
    BaseCacheBackend,
    NullCacheBackend,
    schema_registry,
)
from django_api_factory.queryset import MyQuerySet

logger = logging.getLogger(__name__)


def convert(value):
    """Coerce a value from an API response to a sortable scalar."""
    if not isinstance(value, str):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, fmt).timestamp()
        except (ValueError, TypeError):
            continue
    try:
        return float(value.replace(",", ""))
    except (ValueError, AttributeError):
        return -float("inf") if value == " " else value


def _handle_search_condition(item_value, search_terms, sep):
    """Decide whether one row matches one filter param's value.

    Extracted as a module-level function (Jun 2026 fix for the BigPost-100k
    filter bug) so it's directly unit-testable without spinning up a fake
    admin + network mock. Used by `APIAdmin.get_api_data` and mirrored by
    `APIFilter.choices` in filter.py.

    Semantics:
      - Single term, no `sep` in term: EXACT equality (int-coerced if both
        sides parse as int, else string equality). The previous `'1' in '10'`
        substring-match was the bug — `userId=1` matched userIds 1, 10-19,
        21, 31, ..., 91, 100-199, ... (every userId whose decimal form
        contains '1').
      - Multi-term (e.g. `?userId=1,2`) or single term with the separator
        inside (e.g. `?title=apple\u3001banana`): OR-equals across the terms, with
        the item_value normalized through split-sort-join so multi-valued
        cells (e.g. "apple\u3001banana") compare canonically.
    """
    if len(search_terms) == 1 and sep not in search_terms[0]:
        # Single term, no separator: EXACT equality.
        term = search_terms[0]
        s = str(item_value)
        try:
            return int(s) == int(term)
        except (ValueError, TypeError):
            return s == term
    # Multi-term or single-with-separator: OR-equals, normalized.
    if sep in str(item_value):
        normalized = sep.join(sorted(str(item_value).split(sep)))
    else:
        normalized = str(item_value)
    for term in search_terms:
        t = term.strip()
        if not t:
            continue
        try:
            if int(normalized) == int(t):
                return True
        except (ValueError, TypeError):
            if normalized == t:
                return True
    return False


class APIAdmin(ActionFormMixin, AuditLogMixin, admin.ModelAdmin):
    """
    Admin class for API-backed models. Subclass this and set `model` to your
    APIModel subclass to display external REST data inside Django admin.

    Subclasses typically just set:
        class PostAdmin(APIAdmin):
            list_display = ["id", "title", "body"]
            list_filter = [("userId", APIMultiSelectFilter)]
    """

    #: Template used for API-backed changelist pages.
    change_list_template = "admin/django_api_factory/change_list.html"

    #: Disable Django's "show all" link for API-backed pagination.
    list_max_show_all = 1

    #: Last API queryset built for the current admin instance.
    api_data = None

    #: Last discovered API field list for dynamic admin columns.
    api_list = None

    #: Field list used by export helpers.
    export_list = None

    #: Default page size. Large enough for small APIs, bounded for large APIs.
    list_per_page = 2000

    #: Optional fallback total when the API cannot return a live count.
    expected_total = None

    #: Explicit Django list_filter config; empty means auto-generate filters.
    list_filter = []

    #: API field names excluded from auto-generated filters.
    list_filter_exclude = []

    #: Disable Django's stock search box by default for dynamic API rows.
    search_fields = []

    #: Django admin list_display_links override for dynamic API columns.
    list_display_links = None

    #: API parameter names consumed by subclass-specific URL builders.
    paras_list = []

    #: Deprecated legacy detail cache. Use cache_backend and detail keys.
    user_search_result = {}

    #: Raw API rows used by filter choice generation.
    json_to_filter = None

    #: If True, `get_api_data` caches raw API data via `self.cache_backend`
    #: so `get_object` can resolve detail-view pks without a fresh API call.
    #: Per-(user, model, query-schema) keying isolates multiple users and
    #: multiple models from each other.
    #: Opt-in: defaults to False. Set to True on a per-admin-class basis
    #: when you actually want detail-view caching.
    detail_cache_enabled: bool = False
    #: TTL (seconds) for the detail-view cache. 0 or None disables.
    detail_cache_ttl: int = 300  # 5 min

    #: If True, `get_api_data` reads from the short-term cache (per-user+
    #: model+schema) before calling the API. Catches "I clicked twice
    #: within 5 minutes" repeat requests.
    #: Opt-in: defaults to False.
    changelist_cache_enabled: bool = False
    #: TTL (seconds) for the changelist short-term cache. 0 or None disables.
    changelist_cache_ttl: int = 300  # 5 min

    #: Timeout, in seconds, for outbound API requests.
    request_timeout = 10

    #: Legacy cache TTL in seconds for model-provided cache keys.
    cache_ttl = 300

    #: Cache backend class used for detail, changelist, and distinct caches.
    #: Defaults to `NullCacheBackend`; projects can opt into Redis or another
    #: backend explicitly on each admin class.
    cache_backend_class = NullCacheBackend

    #: Separator used to split multi-value fields in API responses for search.
    multi_value_separator = "\u3001"

    #: GET parameter names that should be normalized by parse_dt().
    date_params: list = []

    def get_object(self, request, object_id, from_field=None):
        """
        Resolve `object_id` for the detail view.

        Tries in order:
        1. Detail cache (T1.5) — fast for the current page's id
        2. **Page-iteration fallback** — for server-side pagination, when
           `object_id` came from a different page (the detail URL has no
           `?p=N` so we don't know which page it was on). Walk pages
           up to the optional `expected_total / page_size` fallback and
           find the row. Without `expected_total`, try the computed page
           as a best effort and avoid unbounded API calls.
        3. Django's default ORM `super().get_object` as a final fallback.

        Returns the matching model instance, or None if not found.
        """
        # Fast path 1: detail cache (keyed by schema, may include the
        # current request's p/o/q — useful for re-clicks in the same page).
        if self.detail_cache_enabled and self.cache_backend is not None:
            cached = self.cache_backend.get(self._detail_cache_key(request))
            if cached:
                try:
                    items = json.loads(cached.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    items = []
                for item in items:
                    if int(item.get("id", -1)) == int(object_id):
                        return self._build_mymodel_from_item(item)

        # Fast path 2: page iteration for server-side pagination.
        # We don't know which page contains `object_id`. If an optional
        # expected_total fallback exists, use it to bound the slow walk.
        try:
            target_id = int(object_id)
        except (TypeError, ValueError):
            target_id = None

        if target_id is not None:
            page_size = self.list_per_page or 50
            total = self.expected_total or 0
            if total > 0:
                max_pages = (total // page_size) + 1
            else:
                max_pages = 1  # best effort

            # Fast path: assume id is in the API's default order
            # (which is id-ascending for JSONPlaceholder / most public
            # APIs). Compute the page directly: page = (id-1)//page_size+1.
            # One API call instead of looping 1..max_pages (which was
            # capped at 100 — failing for any id past page 100 of a
            # 10k+ dataset). NOTE: don't cap by max_pages here — if id
            # is past expected_total, the API will just return an
            # empty page and we fall through to the slow path. Capping
            # blocked id 99999 in a 10k catalog where expected_total
            # was underspecified.
            from django.test import RequestFactory
            target_page = (target_id - 1) // page_size + 1
            if target_page >= 1:
                # Build GET dict preserving multi-values (QueryDict.lists()
                # returns (key, [val, val, ...]) tuples; flatten first).
                get_dict = {k: v[0] if isinstance(v, list) else v
                            for k, v in request.GET.lists()}
                get_dict["p"] = str(target_page)
                fake_req = RequestFactory().get(request.path, get_dict)
                fake_req.user = request.user
                fake_req.session = getattr(request, "session", None)
                mymodels_qs, _ = self.get_api_data(fake_req)
                for obj in (mymodels_qs._result_cache or []):
                    if obj.id == target_id:
                        return obj

            # Slow path: page-iteration fallback (capped). Use when the
            # API's default order doesn't put id in its computed page
            # (e.g. backend sorts by name, not id). Bounded loop so
            # it can't run forever on a misconfigured admin.
            for page in range(1, min(max_pages, 100) + 1):
                # Build a new request with this page forced so get_api_data
                # fetches the right slice.
                from django.test import RequestFactory
                fake_req = RequestFactory().get(
                    request.path,
                    {**dict(request.GET.items()), "p": page},
                )
                fake_req.user = request.user
                fake_req.session = getattr(request, "session", None)
                mymodels_qs, _ = self.get_api_data(fake_req)
                rows = mymodels_qs._result_cache or []
                for obj in rows:
                    if obj.id == target_id:
                        return obj
                # If a page returned fewer rows than page_size, we've
                # exhausted the dataset — stop early.
                if len(rows) < page_size:
                    break

        return None

    def _build_mymodel_from_item(self, item):
        """Reconstruct a model instance from a single raw API item dict.
        Mirrors the construction logic in `get_api_data`.
        """
        schema_registry.register(self.model, list(item.keys()))
        mymodel = self.model(id=int(item.get("id", 0)), pk=int(item.get("id", 0)))
        for field_name, value in item.items():
            if hasattr(self.model, field_name):
                setattr(mymodel, field_name, value)
        return mymodel

    def _detail_cache_key(self, request):
        """
        Per-(user, model, query-schema) cache key.

        The schema portion is derived from the GET params (excluding `p`
        for pagination and `o` for sort, which don't affect detail
        content) so that different filter/search combos don't stomp on
        each other's cache.
        """
        import hashlib
        # QueryDict (Django 5+) returns list values from .items() —
        # flatten to a single-value dict (same as get_api_data).
        paras = {k: v[0] if isinstance(v, list) else v
                 for k, v in request.GET.items()}
        # Drop params that don't change the underlying dataset
        paras.pop("p", None)
        paras.pop("o", None)
        schema = "&".join(f"{k}={v}" for k, v in sorted(paras.items()))
        schema_hash = hashlib.md5(schema.encode("utf-8")).hexdigest()[:16]
        return f"detail:{self.model._meta.label_lower}:{request.user.pk}:{schema_hash}"

    def _changelist_cache_key(self, request):
        """Per-(user, model, page, query-schema) cache key for short-term
        changelist caching. Same scheme as detail but with a `changelist:`
        prefix so the two caches don't collide if both are enabled.

        T2.1 (F4): with server-side pagination, each page is a SEPARATE
        API call, so the cache key INCLUDES `p` and `per_page`. Same
        page / same per_page / same sort / same filters / same user =
        cache hit. Different page = cache miss = fresh API call (which
        is cheap, ~30ms for a 50-row page).
        """
        import hashlib
        # QueryDict (Django 5+) returns list values from .items() —
        # flatten to a single-value dict (same as get_api_data).
        paras = {k: v[0] if isinstance(v, list) else v
                 for k, v in request.GET.items()}
        # ALL params are part of the cache key now, including display
        # params (p / per_page). Real data-affecting params (`o` for
        # sort, `q` for search, `userId` / `title` / etc. for filters)
        # obviously shape the data; p / per_page shape which slice of
        # the API's response we get. Under server-side pagination,
        # these are equivalent.
        schema = "&".join(f"{k}={v}" for k, v in sorted(paras.items()))
        schema_hash = hashlib.md5(schema.encode("utf-8")).hexdigest()[:16]
        return (
            f"changelist:{self.model._meta.label_lower}:"
            f"{request.user.pk}:{schema_hash}"
        )

    @display(description=mark_safe('<input type="checkbox" id="action-toggle">'))
    def action_checkbox(self, obj):
        """Render the row selection checkbox used by Django admin actions."""
        # Django 5 removed django.contrib.admin.helpers.checkbox; render the
        # checkbox input markup directly.
        return mark_safe(
            f'<input type="checkbox" name="_selected_action" value="{obj.id}">'
        )

    def get_search_results(self, request, queryset, search_term):
        """Return API queryset search results without ORM filtering."""
        return queryset, False

    def has_delete_permission(self, request, obj=None):
        """Disable delete actions for read-only API-backed rows."""
        return False

    def has_add_permission(self, request):
        """Disable add actions for read-only API-backed rows."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change actions for read-only API-backed rows."""
        return False

    def has_view_permission(self, request, obj=None):
        """Allow access when the user has Django's view permission."""
        opts = self.opts
        codename = get_permission_codename("view", opts)
        return request.user.has_perm(f"{opts.app_label}.{codename}")

    def get_changelist(self, request, **kwargs):
        """Return the custom ChangeList class used for API pagination."""
        return APIChangeList

    def changelist_view(self, request, extra_context=None):
        """Handle `?ajax_distinct=1` before delegating to the stock
        changelist. The filter UI (load-more button + debounced
        search box) AJAXes back to this endpoint with the current
        field name, optional search term, and offset, and gets a
        JSON payload of distinct values + truncation info. Same
        auth/permissions as the regular changelist."""
        if request.GET.get("ajax_distinct") == "1":
            return self._ajax_distinct(request)
        extra_context = {
            **(extra_context or {}),
            "api_factory_use_elementui_filters": self.use_elementui_filters,
            "api_factory_load_elementui_assets": self.load_elementui_assets,
            "api_factory_elementui_css_url": self.elementui_css_url,
            "api_factory_elementui_js_url": self.elementui_js_url,
            "api_factory_vue_js_url": self.vue_js_url,
        }
        return super().changelist_view(request, extra_context)

    @property
    def use_simpleui_filters(self):
        """Return True when SimpleUI is installed before Django admin."""
        installed_apps = list(getattr(settings, "INSTALLED_APPS", ()))
        try:
            simpleui_index = installed_apps.index("simpleui")
            admin_index = installed_apps.index("django.contrib.admin")
        except ValueError:
            return False
        return simpleui_index < admin_index

    @property
    def use_elementui_filters(self):
        """Return True when the ElementUI filter toolbar is enabled."""
        return getattr(settings, "DJANGO_API_FACTORY_ELEMENTUI_FILTERS", True)

    @property
    def load_elementui_assets(self):
        """Return True when django-api-factory must load ElementUI itself."""
        return self.use_elementui_filters and not self.use_simpleui_filters

    @property
    def vue_js_url(self):
        """Return the Vue runtime URL used when SimpleUI is not active."""
        return getattr(
            settings,
            "DJANGO_API_FACTORY_VUE_JS_URL",
            "https://cdn.jsdelivr.net/npm/vue@2.6.14/dist/vue.min.js",
        )

    @property
    def elementui_js_url(self):
        """Return the ElementUI JavaScript URL used without SimpleUI."""
        return getattr(
            settings,
            "DJANGO_API_FACTORY_ELEMENTUI_JS_URL",
            "https://cdn.jsdelivr.net/npm/element-ui@2.15.14/lib/index.js",
        )

    @property
    def elementui_css_url(self):
        """Return the ElementUI stylesheet URL used without SimpleUI."""
        return getattr(
            settings,
            "DJANGO_API_FACTORY_ELEMENTUI_CSS_URL",
            "https://cdn.jsdelivr.net/npm/element-ui@2.15.14/lib/theme-chalk/index.css",
        )

    def _ajax_distinct(self, request):
        """JSON endpoint for the filter UI to fetch more distinct
        values on demand. Generic (Jun 2026): calls the admin's
        `get_filter_choices(field, request, q, offset, limit)`
        hook and serializes the result. The hook decides HOW to
        implement distinct retrieval:
          - BigPostAdmin → mock /distinct?q=&offset=&limit=
          - PostAdmin (default) → fetch all pages once, cache,
            serve search/load-more from cache
          - Other admins → same default, or override
        """
        from django.http import JsonResponse, HttpResponseBadRequest
        field_name = request.GET.get("field", "")
        if not field_name:
            return HttpResponseBadRequest("Missing ?field=<name>")
        try:
            offset = int(request.GET.get("offset", "0") or "0")
        except (TypeError, ValueError):
            offset = 0
        try:
            default_limit = getattr(self, "filter_distinct_limit", 20)
            limit = int(request.GET.get("limit", str(default_limit)) or default_limit)
        except (TypeError, ValueError):
            limit = getattr(self, "filter_distinct_limit", 20)
        q = request.GET.get("q", "").strip()
        # Generic path: ask the admin's hook. Subclasses decide.
        payload = self.get_filter_choices(field_name, request, q=q,
                                          offset=offset, limit=limit)
        if payload is None:
            # Hook says "I don't support search/load-more" → return
            # empty so the JS hides the load-more button and clears
            # the search results.
            return JsonResponse({
                "values": [], "count": 0, "returned": 0, "truncated": False,
                "error": "distinct not supported for this admin",
            })
        return JsonResponse(payload)

    def get_list_filter(self, request):
        """Build list_filter spec list for the changelist.

        If the user has declared `list_filter` on the admin class,
        honor it (this is the standard Django admin contract — and
        it's the way to mix APIFilter / APIMultiSelectFilter per field.

        Otherwise auto-generate (api_list, APIMultiSelectFilter) for every
        API-returned field except names in `list_filter_exclude`, so choices
        can be picked first and applied in one commit.
        """
        if self.list_filter:
            return self.list_filter
        api_list = self.api_list
        excluded = set(getattr(self, "list_filter_exclude", []) or [])
        return (
            (api, APIMultiSelectFilter)
            for api in api_list
            if api not in excluded
        )

    # --- Filter distinct values (Jun 2026 cross-page filter) -----------
    #
    # The legacy `json_to_filter` only had the current API page's
    # values, so the filter dropdown showed "userId (200)" instead of
    # the real "userId (10_000)" for a 100k dataset. The fix is to
    # fetch the FULL enum from a distinct endpoint and cache it in
    # Redis. Override this method on subclasses whose API supports
    # `/distinct?field=X`; the default returns None and the filter
    # falls back to per-page distinct (legacy behavior, kept so
    # existing subclasses without a distinct endpoint don't break).

    #: Number of distinct filter options loaded per dropdown request.
    filter_distinct_limit = 20

    #: Fully custom distinct endpoint URL. Overrides inferred endpoint logic.
    filter_distinct_url = None

    #: Resource name passed to the default distinct endpoint convention.
    filter_distinct_resource = None

    #: URL path segment used when it differs from filter_distinct_resource.
    filter_distinct_path = None

    #: Query parameter name used for the resource in distinct requests.
    filter_distinct_resource_param = "resource"

    #: Query parameter name used for the field in distinct requests.
    filter_distinct_field_param = "field"

    #: Query parameter name used for search text in distinct requests.
    filter_distinct_q_param = "q"

    #: Query parameter name used for offset pagination in distinct requests.
    filter_distinct_offset_param = "offset"

    #: Query parameter name used for result limits in distinct requests.
    filter_distinct_limit_param = "limit"

    #: TTL in seconds for cached distinct filter values.
    filter_distinct_cache_ttl = 300

    #: Maximum row count the default distinct walker may scan.
    filter_distinct_max_rows = 1000

    def get_filter_choices(self, field_name, request, q="", offset=0, limit=None):
        """Return distinct values for `field_name` (server-side
        search + paginated), or None to fall back to per-page
        legacy.

        Signature (Jun 2026 generalization):
            field_name: which API field to compute distinct for
            request: the active request (for cache namespace + auth)
            q: server-side search term (substring match, case-
               insensitive). Empty string = no search.
            offset: skip this many values (for load-more pagination)
            limit: return at most this many values (defaults to
               `filter_distinct_limit`)

        Returns one of:
            None  — legacy per-page distinct (no search, no load-more)
            {"values": [...], "count": N, "truncated": bool, ...}
                  — paginated search results, `count` is the
                    matching (post-q) total, `truncated` is True
                    if more values exist past `offset+limit`.

        Default impl (Jun 2026): for SMALL datasets (under
        `filter_distinct_max_rows` AND/OR `expected_total`), fetch
        all pages once via `get_api_data`, aggregate, cache, and
        serve search/offset/limit from the cache. For LARGE
        datasets, configure `filter_distinct_resource` (standard
        endpoint) or override `get_filter_distinct_url` (custom
        endpoint shape).
        """
        limit = limit or getattr(self, "filter_distinct_limit", 20)

        server_payload = self._get_server_filter_choices(
            field_name,
            request,
            q=q,
            offset=offset,
            limit=limit,
        )
        if server_payload is not None:
            return server_payload

        # No q and no offset/limit shortcut: try cache or return None.
        if not q and offset == 0:
            full = self._get_filter_distinct_cache(field_name, request)
            if full is not None:
                return self._slice_distinct_payload(full, q, offset, limit)
        # Cap based on expected_total / list_per_page. If the
        # dataset is too large, return None — subclasses should
        # override.
        total = getattr(self, "expected_total", None)
        max_rows = getattr(self, "filter_distinct_max_rows", 1000)
        if total is not None and total > max_rows:
            return None
        # Fetch all pages (bounded by max_rows or expected_total).
        full = self._fetch_all_distinct_values(field_name, request, max_rows)
        if full is None:
            return None
        # Cache the full set (no q applied) for the cap-window.
        self._set_filter_distinct_cache(field_name, request, full)
        return self._slice_distinct_payload(full, q, offset, limit)

    # --- Default get_filter_choices helpers (Jun 2026) -------------------

    def get_filter_distinct_url(self, field_name, request, q="", offset=0, limit=None):
        """Build the server-side distinct URL, or return None.

        Default convention:
            <api-base>/distinct?resource=<resource>&field=<field>
        where `<api-base>` is inferred from `model.urls(...)` and
        `filter_distinct_resource` / `filter_distinct_path`.

        Override this method when the external API uses a different endpoint
        shape, but keep `get_filter_choices()` inherited.
        """
        endpoint = getattr(self, "filter_distinct_url", None)
        resource = getattr(self, "filter_distinct_resource", None)
        if not endpoint:
            if not resource:
                return None
            path = getattr(self, "filter_distinct_path", None) or resource
            try:
                list_url = self.model.urls(page=1, page_size=1)
            except TypeError:
                list_url = self.model.urls()
            marker = f"/{path}"
            if marker not in list_url:
                return None
            endpoint = list_url.split(marker, 1)[0] + "/distinct"

        params = {
            getattr(self, "filter_distinct_field_param", "field"): field_name,
            getattr(self, "filter_distinct_offset_param", "offset"): offset,
            getattr(self, "filter_distinct_limit_param", "limit"): limit,
        }
        resource_param = getattr(self, "filter_distinct_resource_param", "resource")
        if resource and resource_param:
            params[resource_param] = resource
        if q:
            params[getattr(self, "filter_distinct_q_param", "q")] = q
        return self._add_query_params(endpoint, params)

    def _add_query_params(self, url, params):
        """Return `url` with `params` merged into its query string."""
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        for key, value in params.items():
            if key and value not in (None, ""):
                query[key] = str(value)
        return urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        ))

    def _server_filter_choices_cache_key(self, url):
        """Build a cache key for a server-side distinct endpoint URL."""
        import hashlib
        label = "unknown"
        try:
            label = self.model._meta.label_lower
        except AttributeError:
            pass
        h = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
        return f"distinct_endpoint:{label}:{h}"

    def _get_server_filter_choices(
        self,
        field_name,
        request,
        q="",
        offset=0,
        limit=None,
    ):
        """Fetch distinct choices from a configured server-side endpoint."""
        admin_limit = getattr(self, "filter_distinct_limit", 20) or 20
        effective_limit = min(limit or admin_limit, admin_limit)
        url = self.get_filter_distinct_url(
            field_name,
            request,
            q=q,
            offset=offset,
            limit=effective_limit,
        )
        if not url:
            return None

        ttl = getattr(self, "filter_distinct_cache_ttl", 0)
        cache_key = self._server_filter_choices_cache_key(url)
        if ttl and getattr(self, "cache_backend", None):
            try:
                cached = self.cache_backend.get(cache_key)
                if cached:
                    return json.loads(cached.decode("utf-8"))
            except Exception:
                pass

        try:
            response = requests.get(url, timeout=self.request_timeout)
            if response.status_code != 200:
                return None
            payload = response.json()
        except Exception:
            return None

        if isinstance(payload, list):
            payload = {
                "values": payload,
                "count": len(payload),
                "returned": len(payload),
                "truncated": False,
            }
        if not isinstance(payload, dict):
            return None

        if ttl and getattr(self, "cache_backend", None):
            try:
                self.cache_backend.set(
                    cache_key,
                    json.dumps(payload).encode("utf-8"),
                    ttl,
                )
            except Exception:
                pass
        return payload

    def _raw_rows_cache_key(self, max_rows):
        """Redis key for the shared per-admin raw rows cache. All
        distinct lookups within the same admin + max_rows window
        share this cache, so N list_filter fields on one admin → 1
        network walk instead of N. Jun 2026 fix for the per-field
        71-second trap (PostAdmin 3 fields × 12 jsonplaceholder
        pages × cross-Pacific RTT)."""
        import hashlib
        h = hashlib.md5(str(max_rows).encode("utf-8")).hexdigest()[:12]
        # Defensive: tests use APIAdmin.__new__ to skip __init__,
        # so self.model may be missing. Fall back to a generic key
        # rather than crashing — the cache is per-process anyway
        # when cache_backend is the default NoOpCacheBackend.
        label = "unknown"
        try:
            label = self.model._meta.label_lower
        except AttributeError:
            pass
        return f"distinct_raw:{label}:{h}"

    def _fetch_all_raw_rows(self, request, max_rows):
        """Walk all pages of the API ONCE and cache the raw rows
        (list[dict]) shared across all distinct lookups on this
        admin. Bounded by `max_rows` rows total and `expected_total`
        (whichever is smaller). Returns list of dicts, or None on
        fetch failure.

        Jun 2026 rewrite: previous `_fetch_all_distinct_values`
        walked pages per-field, which made PostAdmin (3 fields ×
        12 pages × cross-Pacific jsonplaceholder) take 71 seconds
        on first load. Now N fields share one walk.
        """
        cache_key = self._raw_rows_cache_key(max_rows)
        memory_cache = getattr(self, "_filter_raw_rows_memory_cache", {})
        if cache_key in memory_cache:
            return memory_cache[cache_key]

        current_rows = getattr(self, "json_to_filter", None)
        if isinstance(current_rows, list) and 0 < len(current_rows) <= max_rows:
            memory_cache[cache_key] = current_rows
            self._filter_raw_rows_memory_cache = memory_cache
            return current_rows

        ttl = getattr(self, "filter_distinct_cache_ttl", 0)
        if ttl and getattr(self, "cache_backend", None):
            try:
                import json as _json
                cached = self.cache_backend.get(cache_key)
                if cached:
                    return _json.loads(cached.decode("utf-8"))
            except Exception:
                pass
        # Cache miss — walk all pages once
        try:
            page_size = self._get_effective_per_page(request, self.list_per_page) or 50
        except Exception:
            page_size = 50
        max_pages = (max_rows // page_size) + 2
        total = getattr(self, "expected_total", None) or max_rows
        if total > 0:
            max_pages = min(max_pages, (total // page_size) + 2)
        max_pages = min(max_pages, 200)  # hard cap

        all_rows = []
        seen_pages = 0
        for page in range(1, max_pages + 1):
            try:
                fake_req = self._build_request_for_page(request, page, page_size)
                url = self.get_api_urls(fake_req.GET.copy(), fake_req)
                import requests as _req
                resp = _req.get(url, timeout=self.request_timeout)
                if resp.status_code != 200:
                    break
                data_raw = resp.json()
                # Unwrap envelope: prefer APIModel.parse_response (4 standard
                # shapes). Fall back to the legacy unwrap so non-APIModel
                # models (e.g. test fixtures using plain `models.Model`)
                # still work without an explicit override.
                _parse = getattr(self.model, "parse_response", None)
                if callable(_parse):
                    try:
                        data_raw = _parse(data_raw)
                    except ValueError:
                        break
                elif isinstance(data_raw, dict) and "data" in data_raw:
                    data_raw = data_raw["data"].get("items", [])
                if not data_raw:
                    break
                all_rows.extend(data_raw)
                seen_pages += 1
                if len(data_raw) < page_size:
                    break
                if len(all_rows) >= max_rows:
                    all_rows = all_rows[:max_rows]
                    break
            except Exception:
                break
        if seen_pages == 0:
            return None
        # Cache raw rows for the TTL window. default=str so
        # non-JSON-native values (datetime, Decimal) survive a
        # round-trip.
        if ttl and getattr(self, "cache_backend", None):
            try:
                import json as _json
                self.cache_backend.set(
                    cache_key,
                    _json.dumps(all_rows, default=str).encode("utf-8"),
                    ttl,
                )
            except Exception:
                pass
        memory_cache[cache_key] = all_rows
        self._filter_raw_rows_memory_cache = memory_cache
        return all_rows

    def _fetch_all_distinct_values(self, field_name, request, max_rows):
        """Aggregate distinct values for `field_name` from a single
        shared raw-rows walk. Bounded by `max_rows` rows total and
        `expected_total` (whichever is smaller).

        Jun 2026: delegates to `_fetch_all_raw_rows` so multiple
        list_filter fields share one network walk (no more 71s on
        PostAdmin first load — see `_fetch_all_raw_rows` for the
        before/after story).
        """
        raw_rows = self._fetch_all_raw_rows(request, max_rows)
        if not raw_rows:
            return None
        all_values = set()
        ordered_values = []
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            v = item.get(field_name)
            if v is not None and v not in all_values:
                all_values.add(v)
                ordered_values.append(v)
            if len(all_values) >= max_rows:
                break
        return ordered_values

    def _build_request_for_page(self, request, page, page_size):
        """Clone `request` with `?p=N` forced so `get_api_data`
        fetches the requested page. Used by the default distinct
        walker to iterate pages without changing the user's
        current request."""
        from django.http import HttpRequest
        new_req = HttpRequest()
        new_req.GET = request.GET.copy()
        new_req.GET["p"] = str(page)
        new_req.POST = request.POST
        new_req.method = "GET"
        new_req.path = request.path
        new_req.user = getattr(request, "user", None)
        new_req.META = getattr(request, "META", {})
        return new_req

    def _slice_distinct_payload(self, values, q, offset, limit):
        """Apply q filter + offset/limit slicing to the full distinct
        list. Returns the standard {values, count, truncated, ...}
        dict the AJAX endpoint and template expect.
        """
        if q:
            ql = str(q).lower()
            values = [v for v in values if ql in str(v).lower()]
        total = len(values)
        if offset:
            values = values[offset:]
        if limit:
            sliced = values[:limit]
        else:
            sliced = values
        truncated = (offset + len(sliced)) < total
        return {
            "values": sliced,
            "count": total,
            "returned": len(sliced),
            "truncated": truncated,
        }

    def _filter_distinct_cache_key(self, field_name):
        """Redis key for the full per-field distinct values. Per-
        model, not per-user (the dataset is the same for everyone)."""
        import hashlib
        h = hashlib.md5(field_name.encode("utf-8")).hexdigest()[:12]
        return f"distinct_all:{self.model._meta.label_lower}:{h}"

    def _get_filter_distinct_cache(self, field_name, request):
        """Read cached distinct values for one filter field."""
        ttl = getattr(self, "filter_distinct_cache_ttl", 0)
        if not ttl or not getattr(self, "cache_backend", None):
            return None
        try:
            import json as _json
            cached = self.cache_backend.get(self._filter_distinct_cache_key(field_name))
            if cached:
                return _json.loads(cached.decode("utf-8"))
        except Exception:
            pass
        return None

    def _set_filter_distinct_cache(self, field_name, request, values):
        """Store cached distinct values for one filter field."""
        ttl = getattr(self, "filter_distinct_cache_ttl", 0)
        if not ttl or not getattr(self, "cache_backend", None):
            return
        try:
            import json as _json
            self.cache_backend.set(
                self._filter_distinct_cache_key(field_name),
                _json.dumps(values).encode("utf-8"),
                ttl,
            )
        except Exception:
            pass

    def get_paginator(
        self,
        request,
        queryset,
        per_page,
        orphans=0,
        allow_empty_first_page=True,
    ):
        """
        M2 (T2.1 MVP): return a Paginator that asks the API for the
        current page on each `page(N)` call (server-side pagination).

        Standard Django Paginator assumes `object_list` contains ALL
        rows and slices it per page. For server-side pagination, we
        override `page()` to re-call `get_api_data(request)` which
        builds an API URL with `?page=N&page_size=M` and fetches just
        that page from the API.

        `count` prefers the live `X-Total-Count` captured by
        `get_api_data`, then falls back to optional `expected_total`
        for legacy APIs that cannot return total metadata. Without
        either, count falls back to the size of the current cache.
        """
        from django.core.paginator import Paginator
        from django.utils.functional import cached_property

        class _APIPaginator(Paginator):
            def __init__(self, object_list, per_page, total=0,
                         request=None, admin=None, **kw):
                super().__init__(object_list, per_page, **kw)
                self._total = int(total) if total else 0
                self._request = request
                self._admin = admin

            @cached_property
            def count(self):
                if self._total:
                    return self._total
                return len(self.object_list)

            def page(self, number):
                number = self.validate_number(number)
                if self._request is not None and self._admin is not None:
                    # T2.1 MVP: ask the API for just this page rather
                    # than slicing the cache. Clone the request and force
                    # `?p=number` because ChangeList may clamp an out-of-range
                    # page after filters shrink the result set.
                    from copy import copy
                    from django.contrib.admin.views.main import PAGE_VAR

                    page_request = copy(self._request)
                    page_request.GET = self._request.GET.copy()
                    page_request.GET[PAGE_VAR] = str(number)
                    new_qs, _new_fields = self._admin.get_api_data(page_request)
                    items = list(new_qs)
                    if len(items) > self.per_page:
                        bottom = (number - 1) * self.per_page
                        top = bottom + self.per_page
                        items = items[bottom:top]
                    return self._get_page(items, number, self)
                # Fallback (no request, e.g. direct test): slice whatever
                # the queryset currently holds.
                items = list(self.object_list)
                bottom = (number - 1) * self.per_page
                top = bottom + self.per_page
                return self._get_page(items[bottom:top], number, self)

        # Total row count for the paginator. Priority (Jun 2026):
        # 1. `self._api_filtered_total` — set by `get_api_data` from the
        #    API's X-Total-Count header. Reflects the FILTERED dataset
        #    size (e.g. ?userId=1 on 100k → total=10), so the paginator
        #    shows the right number of pages for the filter.
        # 2. `expected_total` — class attr, the UNFILTERED dataset size
        #    declared on the admin. Use when the API doesn't return
        #    X-Total-Count (no cross-page filter support).
        # 3. len(object_list) — fallback: paginator only knows about
        #    the rows already in the cache.
        total = (
            getattr(self, "_api_filtered_total", None)
            or getattr(self, "expected_total", None)
            or 0
        )
        # `?per_page=N` overrides the class-level `list_per_page` for this
        # request. Used by the per-page selector in the changelist footer.
        per_page = self._get_effective_per_page(request, per_page)
        return _APIPaginator(
            queryset, per_page,
            total=total,
            request=request,        # NEW: needed by page() to re-fetch
            admin=self,             # NEW: needed by page() to call get_api_data
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    def get_queryset(self, request):
        """Return the API-backed queryset for the changelist."""
        # Client-side pagination from cache. `get_api_data` is
        # idempotent across requests that share the same data schema
        # (the cache key strips `p` / `per_page`), so navigating
        # pages or changing per_page just slices the existing cache
        # — no new API call. Only filter / sort / search changes
        # (which DO change the data) trigger a fresh fetch.
        self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        return self.api_data

    def get_api_urls(self, paras, request):
        """Build the external API URL for the current changelist request."""
        # T2.1 MVP: server-side pagination. Pass `?page=N&page_size=M`
        # to the API; the API returns just that page. Django admin's
        # `?p=N` becomes a real API call, not a cache slice.
        #
        # We also keep client-side `p`/`per_page` out of the forwarded
        # params: the API only needs its own pagination/filter args.
        # In-memory filter / sort on the returned page still works as
        # before (now applied to one page instead of the full cache).
        per_page = self._get_effective_per_page(request, self.list_per_page)
        # `?p=garbage` should fall back to page 1, not 500.
        try:
            page = int(paras.get("p", "1") or "1")
        except (TypeError, ValueError):
            page = 1
        if page < 1:
            page = 1
        # Forward everything except the admin's own display params.
        # `o` is Django admin's column-order token; when server-side sort
        # is available we translate it to `_sort` / `_order` above.
        forwarded = {
            k: v for k, v in paras.items() if k not in ("p", "per_page", "o")
        }
        forwarded["page"] = page
        forwarded["page_size"] = per_page
        try:
            return self.model.urls(**forwarded)
        except TypeError:
            # Backwards-compat: if urls() doesn't accept kwargs, call with no args
            return self.model.urls()

    #: Allowed page-size choices for the changelist footer selector.
    PER_PAGE_CHOICES = (10, 25, 50, 100, 200, 500, 2000, 10000)

    def get_per_page_choices(self, effective_per_page=None):
        """Return footer page-size choices including the active page size."""
        choices = set(self.PER_PAGE_CHOICES)
        for value in (self.list_per_page, effective_per_page):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                choices.add(value)
        return tuple(sorted(choices))

    #: Default maximum rows fetched when no live total is available.
    DEFAULT_CACHE_FETCH_SIZE = 1000

    def _get_cache_fetch_size(self, request=None):
        """How many rows to fetch from the API on first load / cache
        miss. With client-side pagination, this is the dataset size
        the user will paginate over.

        Prefer optional `expected_total` when declared for a legacy API;
        otherwise fall back to `DEFAULT_CACHE_FETCH_SIZE` (1000). The
        default covers small APIs and avoids guessing totals for dynamic
        external datasets.
        """
        return getattr(self, "expected_total", None) or self.DEFAULT_CACHE_FETCH_SIZE

    def _get_effective_per_page(self, request, default):
        """Return the active per-page size for a request."""
        if request is None:
            # Direct callers (e.g. tests invoking get_paginator without
            # a request) — no per-page override to read.
            return default
        raw = request.GET.get("per_page", "").strip()
        if raw.isdigit():
            n = int(raw)
            # Cap at 50_000 — covers the 10000 UI choice plus headroom
            # for one-off bulk pulls. Past that, the API server-side
            # pagination is the right answer; the admin HTML table
            # can't sensibly render tens of thousands of rows.
            if 1 <= n <= 50_000:
                return n
        return default

    # --- Date param parsing helpers -----------------------------------------

    def parse_dt(self, raw):
        """
        Parse an admin date_hierarchy string (e.g. "Today Jun 5 2026" or
        "Jun 5 2026") into "YYYYMMDD" format. Returns "" if `raw` is empty
        or unparseable.

        Subclasses can override this to support different input formats
        (e.g. ISO "2026-06-05" or epoch). The default handles the format
        Django admin produces from its date_hierarchy widget.
        """
        if not raw:
            return ""
        try:
            # Django admin date_hierarchy format: "<relative-word> <Mon DD YYYY>"
            # e.g. "Today Jun 5 2026" or "Yesterday Jun 4 2026". Strip the first
            # token (relative word) and keep the date portion.
            parts = raw.split(" ")
            if len(parts) >= 4:
                date_part = " ".join(parts[1:4])
            else:
                date_part = raw
            return datetime.datetime.strptime(date_part, "%b %d %Y").strftime("%Y%m%d")
        except (ValueError, TypeError, IndexError):
            return ""

    def parse_paras(self, paras):
        """
        Return a copy of `paras` with each `date_params` entry converted
        via `parse_dt`. Non-date params pass through unchanged.

        Example::

            class TashareAdmin(APIAdmin):
                date_params = ['dt']
                def get_api_urls(self, paras, request):
                    paras = self.parse_paras(paras)
                    return f'...&dt={paras.get("dt", "")}'
        """
        if not self.date_params:
            return dict(paras)
        result = dict(paras)
        for name in self.date_params:
            if name in result:
                result[name] = self.parse_dt(result[name])
        return result

    def _resolve_expected_total(self, paras, request):
        """
        M2 (T2.2): figure out the total row count for server-side pagination.
        Returns the class attr (kept for backwards compat with subclasses
        that override `get_expected_total`).
        """
        if hasattr(self, "get_expected_total"):
            return self.get_expected_total(paras, request)
        return getattr(self, "expected_total", None)

    def _extract_response_total(self, response_data):
        """Best-effort total extraction for real APIs without count headers.

        Supported common shapes:
        - `{"total": 208, "users": [...]}`
        - `{"count": 208, "results": [...]}`
        - `{"meta": {"results": {"total": 20328575}}, "results": [...]}`
        - `{"pagination": {"total": 208}, "data": [...]}`
        """
        if not isinstance(response_data, dict):
            return None
        candidates = [
            response_data.get("total"),
            response_data.get("count"),
        ]
        meta = response_data.get("meta")
        if isinstance(meta, dict):
            meta_results = meta.get("results")
            if isinstance(meta_results, dict):
                candidates.append(meta_results.get("total"))
            candidates.append(meta.get("total"))
        pagination = response_data.get("pagination")
        if isinstance(pagination, dict):
            candidates.append(pagination.get("total"))
        for value in candidates:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return None

    @property
    def cache_backend(self) -> Optional[BaseCacheBackend]:
        """
        Build (and cache for the request) the configured cache backend.

        Resolution: simply `self.cache_backend_class()` (default is
        `NullCacheBackend` — a no-op). To use Redis, opt in explicitly
        with `cache_backend_class = RedisCacheBackend` on the admin class.

        No auto-detection of Django settings. The library does NOT pick
        a backend based on REDIS_HOST — opt-in is intentional.
        """
        if not hasattr(self, "_cache_backend_inst"):
            cls = self.cache_backend_class
            try:
                self._cache_backend_inst = cls()
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Cache backend init failed: %s — falling back to NullCacheBackend",
                    exc,
                )
                self._cache_backend_inst = NullCacheBackend()
        return self._cache_backend_inst

    def _get_cache_data(self, paras):
        """
        Try the configured cache backend; return None on miss / error.

        Uses `self.cache_backend` (auto-built from `cache_backend_class` +
        Django settings) so the core library does not hardcode redis-py.
        """
        try:
            cache_key_prefix = self.model.cache(**paras)
        except TypeError:
            try:
                cache_key_prefix = self.model.cache()
            except Exception:
                cache_key_prefix = None
        if not cache_key_prefix:
            return None
        backend = self.cache_backend
        if backend is None:
            return None
        dt = paras.get("dt", "")
        dt = " ".join(dt.split(" ")[1:4]) if dt else ""
        if dt:
            try:
                dt = datetime.datetime.strptime(dt, "%b %d %Y").strftime("%Y%m%d")
            except ValueError:
                dt = datetime.date.today().strftime("%Y%m%d")
        else:
            dt = datetime.date.today().strftime("%Y%m%d")
        cached = backend.get(f"{cache_key_prefix}{dt}")
        if cached:
            return json.loads(cached.decode("utf-8"))
        return None

    def get_api_data(self, request):
        """Fetch, parse, filter, sort, and wrap API rows as a QuerySet."""
        # ModelAdmin instances are reused, so never let a previous request's
        # X-Total-Count leak into an API response/cache path without that header.
        if hasattr(self, "_api_filtered_total"):
            delattr(self, "_api_filtered_total")

        # A single Django admin changelist render can ask for queryset,
        # list_display, filters, and paginator data through separate hooks.
        # They all describe the same browser request, so only the first call
        # should hit the external API; later calls reuse this request-local
        # result. This intentionally does not persist across page refreshes.
        request_cache_key = None
        request_cache = getattr(
            request,
            "_django_api_factory_api_data_cache",
            None,
        )
        if request_cache is None:
            request_cache = {}
            setattr(
                request,
                "_django_api_factory_api_data_cache",
                request_cache,
            )
        try:
            normalized_get = request.GET.copy()
            try:
                page = int(normalized_get.get("p", "1") or "1")
            except (TypeError, ValueError):
                page = 1
            if page < 1:
                page = 1
            normalized_get["p"] = str(page)
            normalized_get["per_page"] = str(
                self._get_effective_per_page(request, self.list_per_page)
            )
            normalized_query = tuple(
                (key, tuple(normalized_get.getlist(key)))
                for key in sorted(normalized_get)
            )
            request_cache_key = (
                self.model._meta.label_lower,
                getattr(request, "path", ""),
                normalized_query,
            )
        except AttributeError:
            request_cache_key = None
        if request_cache_key is not None and request_cache_key in request_cache:
            cached_rows, cached_fields, cached_data, cached_total = (
                request_cache[request_cache_key]
            )
            self.json_to_filter = list(cached_data)
            if cached_total is not None:
                self._api_filtered_total = cached_total
            cached_qs = MyQuerySet(model=self.model)
            cached_qs._result_cache = list(cached_rows)
            return cached_qs, list(cached_fields)

        # QueryDict (Django 5+ MultiValueDict) returns list values from
        # `.items()` — flatten to single-value dict so downstream code
        # can treat each param as a plain string. (Django <5 returned
        # single values; old admin code assumed that.)
        paras = {k: v[0] if isinstance(v, list) else v
                 for k, v in request.GET.items()}

        order_list = paras.get("o", "").split(".") if paras.get("o") else []
        tmp_order_list = []
        # Note: previously gated on `if self.actions:` which silently
        # skipped the col-idx → field-ref conversion on action-less
        # admins (BigPostAdmin, CoinAdmin). The in-memory sort still
        # worked (no-op pass for unknown idx), but server-side sort
        # translation (added Jun 2026 for cross-page ordering) read
        # the un-converted idx and went to the wrong field. Moved
        # out of the actions gate so the conversion is unconditional.
        for i in order_list:
            try:
                n = int(i)
            except ValueError:
                continue
            # Map Django admin's `?o=N` (UI column idx, 0-based,
            # points at list_display[N]) to a field reference. The
            # UI checkbox column is NOT counted in `?o=N`; N=0 is
            # the first list_display element. So:
            #   ?o=0 → list_display[0] = `__str__` (= id, special)
            #   ?o=1 → first data field (fields[0])
            #   ?o=2 → fields[1], ?o=3 → fields[2], ...
            # The legacy conversion used `n - 2` (assuming 1-indexed
            # + `__str__` ate col 1) which was OFF-BY-ONE: clicking
            # the Title column emits `?o=2` but framework sorted by
            # `fields[0]` (userId). User-visible bug. Fix: use `n - 1`.
            if n == 0:
                # Sort by the pk/id that `__str__` displays.
                tmp_order_list.append("id")
            elif n == -1:
                tmp_order_list.append("-id")
            elif n > 0:
                # n=1 → fields[0], n=2 → fields[1], n=3 → fields[2]
                tmp_order_list.append(str(n - 1))
            elif n < -1:
                # n=-2 → fields[0] desc, n=-3 → fields[1] desc, etc.
                tmp_order_list.append("-" + str(-(n + 1)))
            order_list = tmp_order_list

        # Server-side sort (Jun 2026 cross-page sort): translate the
        # FIRST sort key from Django admin's `?o=N` (UI column idx) to
        # the API's `?_sort=<field>&_order=<asc|desc>` convention. This
        # way the API returns rows in sort order across all pages,
        # not just the current 50 rows. JSONPlaceholder / mock server
        # both honor `?_sort` / `?_order` (mock server: see
        # spikes/big-data-mock/server.py).
        #
        # We translate only the first sort key (single-column sort,
        # the common case). Multi-column sort (`?o=1.0,2.0`) falls
        # back to client-side sort on the current page — documented
        # limitation.
        #
        # Cold start: `self.api_list` is set on the second request
        # onward (first request goes through get_list_display → get_api_data
        # → sets self.api_list). On the first request we don't know
        # the field names yet, so server-side sort is skipped and the
        # legacy client-side sort path handles the in-page ordering.
        if order_list and getattr(self, "api_list", None):
            first = order_list[0]
            if first in ("id", "-id"):
                sort_field, sort_dir = "id", "desc" if first.startswith("-") else "asc"
            else:
                try:
                    idx = abs(int(first))
                    if idx < len(self.api_list):
                        sort_field = self.api_list[idx]
                        sort_dir = "desc" if first.startswith("-") else "asc"
                    else:
                        sort_field = None
                except (ValueError, TypeError):
                    sort_field = None
            if sort_field:
                paras["_sort"] = sort_field
                paras["_order"] = sort_dir

        # Short-term cache lookup (T1.5b opt-in): catches "I clicked twice
        # within 5 minutes" repeat requests. Opt-in via
        # `changelist_cache_enabled = True` on the admin class. Default off.
        short_cache_data = None
        if (
            self.changelist_cache_enabled
            and self.changelist_cache_ttl
            and self.cache_backend is not None
        ):
            cached = self.cache_backend.get(self._changelist_cache_key(request))
            if cached:
                try:
                    short_cache_data = json.loads(cached.decode("utf-8"))
                    self.json_to_filter = short_cache_data
                except (ValueError, UnicodeDecodeError):
                    short_cache_data = None

        # Cache lookup (legacy T1.2 cache)
        if short_cache_data is not None:
            data = short_cache_data
        else:
            data = self._get_cache_data(paras)
        if data is not None:
            self.json_to_filter = data
        else:
            try:
                response = requests.get(
                    self.get_api_urls(paras, request),
                    timeout=self.request_timeout,
                )
                if response.status_code == 200:
                    data = json.loads(response.content)
                    body_total = self._extract_response_total(data)
                    if body_total is not None:
                        self._api_filtered_total = body_total
                    # Unwrap envelope: prefer APIModel.parse_response (4 standard
                    # shapes). Fall back to the legacy unwrap so non-APIModel
                    # models (e.g. test fixtures using plain `models.Model`)
                    # still work without an explicit override.
                    _parse = getattr(self.model, "parse_response", None)
                    if callable(_parse):
                        try:
                            data = _parse(data)
                        except ValueError as exc:
                            logger.warning("APIAdmin.get_api_data: %s", exc)
                            return None
                    elif isinstance(data, dict) and "data" in data:
                        data = data["data"].get("items", [])
                    self.json_to_filter = data
                    # X-Total-Count (Jun 2026 cross-page filter): real APIs
                    # like JSONPlaceholder return this header. When the API
                    # server-side filters (e.g. ?userId=1), the total in
                    # the header is the FILTERED size, which the paginator
                    # needs to render the right number of pages. Store on
                    # `self` so `get_paginator` can pick it up.
                    xtc = response.headers.get("X-Total-Count")
                    if xtc and xtc.isdigit():
                        self._api_filtered_total = int(xtc)
                else:
                    messages.add_message(
                        request,
                        messages.ERROR,
                        f"API returned {response.status_code}",
                    )
                    data = []
            except requests.RequestException as exc:
                messages.add_message(request, messages.ERROR, f"Request failed: {exc}")
                data = []
            except json.JSONDecodeError as exc:
                messages.add_message(
                    request,
                    messages.ERROR,
                    f"JSON parse failed: {exc}",
                )
                data = []

        if data:
            fields = []
            [fields.append(j) for j in data[0] if j not in fields]
        else:
            fields = ["id"]
        fields = [i for i in fields if i not in self.model.black_fields]

        if order_list:
            locale.setlocale(locale.LC_ALL, "")
            sort_keys = []
            sort_orders = []
            for i in order_list:
                # `id` / `-id` are the special pk reference produced by the
                # conversion for UI col 1 (`__str__` display). Other entries
                # are integer indices into `fields`.
                if i in ("id", "-id"):
                    sort_keys.append("id")
                    sort_orders.append(1 if i[0] != "-" else -1)
                    continue
                try:
                    idx = abs(int(i))
                except ValueError:
                    continue
                if idx >= len(fields):
                    continue
                sort_keys.append(fields[idx])
                sort_orders.append(1 if i[0] != "-" else -1)
            if sort_keys:
                # Sort key construction:
                # - For string-valued fields, `sort_orders[i] * convert(x[k])`
                #   is a no-op (we keep the raw string for natural ordering)
                #   — so DESC direction gets LOST on string keys.
                # - For numeric/date values, multiplying flips the sign and
                #   `sorted()` puts them in the right order.
                # When ALL sort_orders agree (the common case: single column),
                # use `reverse=` in `sorted()` so the direction is honored for
                # BOTH numeric and string keys. Multi-column with mixed
                # directions falls back to the multiply trick (works for
                # numbers only; mixed-type tuple comparison would TypeError
                # anyway).
                all_same = len(set(sort_orders)) == 1
                try:
                    if all_same:
                        data = sorted(
                            data,
                            key=lambda x: tuple(
                                convert(x[k]) for k in sort_keys
                            ),
                            reverse=(sort_orders[0] == -1),
                        )
                    else:
                        data = sorted(
                            data,
                            key=lambda x: tuple(
                                convert(x[k])
                                if isinstance(convert(x[k]), (str, type(None)))
                                else sort_orders[i] * convert(x[k])
                                for i, k in enumerate(sort_keys)
                            ),
                        )
                except TypeError:
                    messages.add_message(
                        request,
                        messages.INFO,
                        "This column cannot be sorted yet",
                    )

        # Dynamically add fields to the model class
        # Register fields on the model class via the module-level
        # SchemaRegistry (T1.3). The registry is idempotent and thread-safe
        # — first request adds the fields, all subsequent requests skip
        # the add_to_class loop entirely.
        schema_registry.register(self.model, fields)
        for field_name in self.paras_list:
            if (
                field_name not in ("q", "o")
                and not schema_registry.is_registered(self.model, field_name)
            ):
                schema_registry.register(self.model, [field_name])
            if field_name in paras:
                del paras[field_name]

        def handle_search_condition(item_value, search_terms):
            return _handle_search_condition(
                item_value, search_terms, self.multi_value_separator
            )

        mymodels = []
        # filter — otherwise `?all=` or `?o=1.0` would be treated as a
        # search field name and zero out the result list (`'all' in item`
        # is always False).
        from django.contrib.admin.views.main import (
            ALL_VAR, ORDER_VAR, PAGE_VAR,
        )
        reserved = {ALL_VAR, ORDER_VAR, PAGE_VAR, "dt"}
        # `SEARCH_VAR` (`q`) is NOT in `reserved` — we want the search box
        # to filter the in-memory data.
        # `per_page` (the per-page selector's URL param) is also reserved
        # — see `APIADMIN_RESERVED_GET_PARAMS` in changelist.py.
        reserved |= APIADMIN_RESERVED_GET_PARAMS
        # `SEARCH_VAR` (`q`) is NOT in `reserved` — we want the search box
        # to filter the in-memory data.
        # Django admin's internal GET params that we must NEVER treat as
        # data filters. Specifically `_changelist_filters` is added by
        # Django when you click a row from a filtered changelist (it
        # preserves the filter state on the detail view). Treating it
        # as a field silently zeroes out the result list → detail view
        # shows "doesn't exist".
        reserved |= {
            "_changelist_filters",  # detail-back-link state preservation
            "_selected_action",      # action-form checkboxes
            "_sort",                # server-side sort field (Jun 2026)
            "_order",               # server-side sort direction (Jun 2026)
            "sort",                 # alternate server-side sort field name
            "order",                # alternate server-side sort direction
        }
        search_pars = {
            k: v for k, v in paras.items()
            if k not in reserved
        }


        for i, item in enumerate(data, start=1):
            # The `q` GET param (search box) should be a sub-string match
            # across all string-valued fields. Other params (legacy
            # list_filter behaviour) are matched by exact field name.
            if "q" in search_pars:
                q = search_pars["q"]
                # ANY-string-field-contains-q semantics, case-insensitive.
                # The previous `all()` made `?q=foo` return 0 rows
                # whenever any string field lacked the substring, and
                # the case-sensitive `in` made `?q=graham` miss
                # "Leanne Graham" (capital G). Normalize both sides
                # to lower-case for a robust substring search.
                q_lc = q.lower()
                field_matches = any(
                    q_lc in str(v).lower()
                    for v in item.values() if isinstance(v, str)
                )
            else:
                field_matches = all(
                    field_name in item
                    and handle_search_condition(
                        str(item[field_name]),
                        search_pars[field_name].split(","),
                    )
                    for field_name in search_pars
                )
            if field_matches:
                # Use the API's real `id` field if present — otherwise fall
                # back to the enumeration index. Falling back to the
                # enumerate index would collide across pages (page 1 ids
                # 1-10, page 2 ids also 1-10) and break detail-view links.
                real_id = item.get("id", i)
                mymodel = self.model(id=real_id, pk=real_id)
                for field_name in fields:
                    if field_name in item:
                        setattr(mymodel, field_name, item[field_name])
                mymodels.append(mymodel)

        mymodels_qs = MyQuerySet(model=self.model)
        mymodels_qs._result_cache = mymodels

        # The original code used action_flag=4 to audit changelist queries. That is a
        # business-specific assumption and is no longer hardcoded here —
        # subclasses can override `log_query` to record their own audit.
        self.log_query(request, self.model.__name__)

        # Cache raw API data via the pluggable cache backend (T1.5) so that
        # `get_object` (detail view) can resolve `object_id` without a
        # fresh API call. This avoids stale-data risk: when the API changes,
        # the user reloads the changelist and the cache is overwritten.
        if (
            self.detail_cache_enabled
            and self.detail_cache_ttl  # 0 or None disables caching
            and self.cache_backend is not None
        ):
            self.cache_backend.set(
                self._detail_cache_key(request),
                json.dumps(data).encode("utf-8"),
                self.detail_cache_ttl,
            )
        # Short-term changelist cache: also write if enabled. The TTL is
        # typically shorter than the detail cache; default 5 min.
        if (
            self.changelist_cache_enabled
            and self.changelist_cache_ttl
            and self.cache_backend is not None
        ):
            self.cache_backend.set(
                self._changelist_cache_key(request),
                json.dumps(data).encode("utf-8"),
                self.changelist_cache_ttl,
            )
        # M2 (T2.1): server-side pagination. The API has already returned
        # the slice for the current page (URL built with `?_page=N&_limit=M`
        # in `get_api_urls`), so `mymodels_qs` is exactly that page's rows.
        # The custom `_APIPaginator.page()` returns the cache as-is, and
        # `count` reads X-Total-Count / optional expected_total. Do NOT
        # slice `mymodels_qs` in
        # memory here — slicing `[N*page : N*page+N]` on a cache that only
        # has `page_size` items would zero out every page beyond the first.
        # (The old client-side slicing was removed; the `?p=` param is
        # consumed in `get_api_urls` to build the request URL.)
        if request_cache_key is not None:
            request_cache[request_cache_key] = (
                list(mymodels),
                list(fields),
                list(data),
                getattr(self, "_api_filtered_total", None),
            )
        return mymodels_qs, fields

    def get_list_display(self, request):
        """Return dynamic list_display fields discovered from the API."""
        if not self.api_list:
            self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        return self.api_list


class APINoDataAdmin(APIAdmin):
    """
    Variant of APIAdmin that does not fetch data on changelist load.
    Use this when the API is expensive or rate-limited and you only want
    results after the user applies a search/filter.
    """

    def get_list_display(self, request):
        return ["id"]
