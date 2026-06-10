"""Tests for M2 server-side pagination (T2.1 MVP).

MVP scope: `get_api_urls` forwards `?page=N&page_size=M` to the API;
`_APIPaginator.page(N)` re-calls `get_api_data(request)` to fetch the
current page from the API. Filter / sort still happens client-side on
the returned page (no cross-page filtering — known MVP trade-off, see
SPIKE_REPORT.md).
"""

import json
import pytest
from unittest.mock import patch, MagicMock
import requests as real_requests

from django.test import RequestFactory

from django_api_factory.admin import APIAdmin
from django_api_factory.models import APIModel
from django_api_factory.queryset import MyQuerySet
from django_api_factory.mixins import schema_registry


# --- Test fixtures --------------------------------------------------------

class PagedPost(APIModel):
    app_label = "tests"

    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs):
        return f"https://example.com/posts?page={page}&page_size={page_size}"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta:
        app_label = "tests"


# --- get_api_urls forwards page + page_size to API (T2.1 MVP) ------------

def test_get_api_urls_passes_request_page_to_api():
    """Server-side pagination: the user's `?p=N` is the page we ask
    the API for (not display-only anymore). The API gets `page=N`."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 100
    req = RequestFactory().get("/admin/tests/pagedpost/?p=3&per_page=20")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com/posts?page=3&page_size=20"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({"p": "3", "per_page": "20"}, req)
    assert captured_kwargs["page"] == 3, (
        f"page should track the request's ?p=, got {captured_kwargs['page']}"
    )
    # per_page from URL also wins over the class default
    assert captured_kwargs["page_size"] == 20


def test_get_api_urls_uses_list_per_page_when_no_per_page_param():
    """No `?per_page=` in URL → API gets page_size = class list_per_page."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/?p=2")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com/posts"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({"p": "2"}, req)
    assert captured_kwargs["page"] == 2
    assert captured_kwargs["page_size"] == 50


def test_get_api_urls_defaults_to_page_1_when_no_p_param():
    """No `?p=` in URL → page=1 (first page)."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com/posts"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({}, req)
    assert captured_kwargs["page"] == 1
    assert captured_kwargs["page_size"] == 50


def test_get_api_urls_strips_p_and_per_page_from_other_params():
    """`p` / `per_page` are admin display params, not for the API.
    They should NOT be forwarded as-is (they get transformed to
    page / page_size). The forwarding dict shouldn't double-include
    them under the old keys."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/?p=2&per_page=20&q=foo")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com/posts"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({"p": "2", "per_page": "20", "q": "foo"}, req)
    # The transformed keys (page / page_size) are present
    assert captured_kwargs["page"] == 2
    assert captured_kwargs["page_size"] == 20
    # q is forwarded (filter params travel through)
    assert captured_kwargs.get("q") == "foo"


def test_get_api_urls_handles_invalid_page_value():
    """`?p=garbage` → page=1 (don't crash, don't 500)."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/?p=garbage")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({"p": "garbage"}, req)
    assert captured_kwargs["page"] == 1


def test_get_api_urls_handles_empty_p_value():
    """`?p=` (empty) → page=1."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/?p=")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls({"p": ""}, req)
    assert captured_kwargs["page"] == 1


def test_get_api_urls_falls_back_when_urls_takes_no_kwargs():
    """Backwards-compat: if `urls()` doesn't accept kwargs, call with no args."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    req = RequestFactory().get("/admin/tests/pagedpost/?p=3")
    # Override urls() to a no-kwargs version (legacy shape)
    admin.model.urls = classmethod(lambda cls: "https://example.com/legacy")
    url = admin.get_api_urls({"p": "3"}, req)
    assert url == "https://example.com/legacy"


# --- Django 5+ QueryDict regression --------------------------------------

def test_get_api_data_flattens_querydict_list_values():
    """Django 5+ QueryDict.items() returns (key, [val]) not (key, val).
    `get_api_data` must flatten list values to single strings, otherwise
    `int(['2'])` raises and `?p=2` silently falls back to page=1.

    Bug: post T2.1 MVP, all PostAdmin pages rendered page=1's data
    because dict(request.GET.items()) stored 'p': ['2'] (list), and
    `int(['2'])` was caught by the fallback `try/except ValueError`,
    silently setting page=1. The user saw the same 10 rows on every
    page navigation."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    # Use a real RequestFactory request so we exercise QueryDict behavior
    req = RequestFactory().get("/admin/tests/pagedpost/?p=2")
    captured_kwargs = {}
    def fake_urls(**kwargs):
        captured_kwargs.update(kwargs)
        return "https://example.com/posts"
    admin.model.urls = classmethod(lambda cls, **kw: fake_urls(**kw))
    admin.get_api_urls(dict(req.GET.items()), req)
    # The captured page param must be int 2, not the list ['2']
    assert captured_kwargs["page"] == 2, (
        f"page should be int 2, got {captured_kwargs['page']!r} — "
        f"QueryDict list bug regressed"
    )


# --- get_object detail-view fallback (F1.1: ?p=越界 detail) ---------------

def test_get_object_uses_id_to_page_direct_lookup():
    """get_object should compute the page directly from the id
    (page = (id-1) // page_size + 1) and fetch that one page — not
    loop 1..100 cap. Without this, an id in page 2000 of a 100k
    dataset (e.g. id=99999, per_page=50) returns 404 because the
    cap stops the loop at page 100."""
    from django_api_factory.queryset import MyQuerySet
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 100_000
    admin.detail_cache_enabled = False
    admin.changelist_cache_enabled = False
    admin.cache_backend_class = type("NullCB", (), {})
    # Stub get_api_data to record what page it was called with
    pages_requested = []

    def fake_get_api_data(req):
        # Extract target_page from the synthetic request
        p = int(req.GET.get("p", "1") or "1")
        pages_requested.append(p)
        # Simulate id range: page 1 = ids 1-50, page 2 = 51-100, ...
        bottom = (p - 1) * 50 + 1
        top = p * 50
        ids = list(range(bottom, top + 1))
        qs = MyQuerySet(model=PagedPost)
        qs._result_cache = []
        for i in ids:
            obj = PagedPost(id=i, pk=i)
            qs._result_cache.append(obj)
        return qs, ["id"]

    admin.get_api_data = fake_get_api_data

    # Detail view: ask for id=99999 (which is in page 2000)
    req = RequestFactory().get("/admin/tests/pagedpost/99999/")
    req.user = type("U", (), {"pk": 1})()
    obj = admin.get_object(req, "99999")
    assert obj is not None, "id=99999 should resolve to a model instance"
    assert obj.id == 99999
    # Direct page lookup: one API call to page 2000
    assert pages_requested == [2000], (
        f"Expected one API call to page 2000, got {pages_requested}"
    )


def test_get_object_returns_none_when_id_beyond_expected_total():
    """get_object should return None (404) when id > expected_total
    instead of looping forever or 500-ing."""
    from django_api_factory.queryset import MyQuerySet
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 100
    admin.detail_cache_enabled = False
    admin.cache_backend_class = type("NullCB", (), {})

    def fake_get_api_data(req):
        qs = MyQuerySet(model=PagedPost)
        # Page 1: ids 1-50
        qs._result_cache = []
        for i in range(1, 51):
            obj = PagedPost()
            obj.id = i
            obj.pk = i
            qs._result_cache.append(obj)
        return qs, ["id"]
    admin.get_api_data = fake_get_api_data

    req = RequestFactory().get("/admin/tests/pagedpost/9999/")
    req.user = type("U", (), {"pk": 1})()
    obj = admin.get_object(req, "9999")
    assert obj is None, "id way beyond expected_total should return None"


# --- _APIPaginator.page(N) re-fetches via get_api_data -------------------

def test_apipaginator_page_calls_get_api_data_for_that_page():
    """page(N) calls admin.get_api_data(request) — the API gets re-asked
    for that page, instead of slicing the cache."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 1000

    # Fake get_api_data — returns a fresh queryset each time
    page_requests = []

    def fake_get_api_data(request):
        # Record what page was asked for
        p = int(request.GET.get("p", "1") or "1")
        page_requests.append(p)
        # Build a queryset of synthetic rows for this page
        qs = MyQuerySet(model=PagedPost)
        qs._result_cache = [f"row-{p}-{i}" for i in range(10)]
        return qs, ["id"]

    admin.get_api_data = fake_get_api_data

    qs_initial = MyQuerySet(model=PagedPost)
    qs_initial._result_cache = [f"row-1-{i}" for i in range(10)]

    req = RequestFactory().get("/admin/tests/pagedpost/?p=3")
    p = admin.get_paginator(req, qs_initial, 50)
    page_3 = p.page(3)

    # get_api_data was called with the request (which has p=3 in GET)
    assert page_requests == [3], (
        f"Expected get_api_data called once with p=3, got {page_requests}"
    )
    # The returned page holds the API's response (rows for p=3)
    assert list(page_3.object_list) == [f"row-3-{i}" for i in range(10)]


def test_apipaginator_page1_first_load_no_extra_get_api_data_call():
    """When the ChangeList first constructs the paginator and calls
    page(1), the API has ALREADY been called once (by get_queryset
    → get_api_data). page(1) on top of that re-fetches — that's the
    MVP's known extra call. (This is the cost of the MVP; F-version
    would re-use the existing cache.)"""
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 1000

    page_requests = []

    def fake_get_api_data(request):
        p = int(request.GET.get("p", "1") or "1")
        page_requests.append(p)
        qs = MyQuerySet(model=PagedPost)
        qs._result_cache = [f"row-{p}-{i}" for i in range(10)]
        return qs, ["id"]

    admin.get_api_data = fake_get_api_data
    qs_initial = MyQuerySet(model=PagedPost)
    qs_initial._result_cache = [f"row-1-{i}" for i in range(10)]

    req = RequestFactory().get("/admin/tests/pagedpost/")
    p = admin.get_paginator(req, qs_initial, 50)
    list(p.page(1).object_list)

    # page(1) re-fetches page 1 (get_api_data was already called
    # separately by get_queryset; this is the known MVP double-call).
    assert 1 in page_requests


def test_apipaginator_count_uses_expected_total():
    """count is expected_total, not len(cache). The cache is just
    the current page (10 rows); the paginator should still know
    there are 1000 rows total so it can render 200 page links."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.expected_total = 1000
    qs = MyQuerySet(model=MagicMock())
    qs._result_cache = list(range(10))  # only 10 cached

    p = admin.get_paginator(None, qs, 50)
    assert p.count == 1000


def test_apipaginator_count_falls_back_to_cache_size_when_no_expected_total():
    """No expected_total → count = len(object_list) (best we can do)."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.expected_total = 0
    qs = MyQuerySet(model=MagicMock())
    qs._result_cache = list(range(50))

    p = admin.get_paginator(None, qs, 50)
    assert p.count == 50


def test_apipaginator_pages_consistent_with_expected_total():
    """num_pages = ceil(expected_total / per_page) — paginator renders
    the right number of page links even though only one page is in
    the cache at a time."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.expected_total = 100
    qs = MyQuerySet(model=MagicMock())
    qs._result_cache = list(range(10))

    p = admin.get_paginator(None, qs, 10)
    assert p.count == 100
    assert p.num_pages == 10


# --- get_expected_total backwards compat --------------------------------

def test_get_expected_total_method_overrides_attr():
    admin = APIAdmin.__new__(APIAdmin)
    admin.expected_total = 1000
    admin.get_expected_total = lambda paras, request: 500
    req = RequestFactory().get("/admin/tests/pagedpost/")
    assert admin._resolve_expected_total({}, req) == 500


# --- MyQuerySet shape (unchanged) ---------------------------------------

def test_myqueryset_len_falls_back_to_result_cache():
    qs = MyQuerySet(model=MagicMock())
    qs._result_cache = [1, 2, 3, 4, 5]
    assert len(qs) == 5


def test_myqueryset_count_returns_result_cache_size():
    qs = MyQuerySet(model=MagicMock())
    qs._result_cache = [1, 2, 3]
    assert qs.count() == 3


# --- PER_PAGE_CHOICES + _get_effective_per_page (Jun 2026: bumped to 10k) --

def test_per_page_choices_includes_large_values():
    """PER_PAGE_CHOICES must include 2000 and 10000 for the big-dataset
    stress-test scenario (BigPost / OpenAlex / etc.). The old tuple only
    went up to 200, which was a ceiling for a 100-row Post dataset."""
    from django_api_factory.admin import APIAdmin
    assert 2000 in APIAdmin.PER_PAGE_CHOICES
    assert 10_000 in APIAdmin.PER_PAGE_CHOICES
    # And we didn't drop the small values
    for v in (10, 25, 50, 100, 200):
        assert v in APIAdmin.PER_PAGE_CHOICES, f"lost {v} from PER_PAGE_CHOICES"


def test_get_effective_per_page_accepts_2000_and_10000():
    """The validator must accept 2000 and 10000 from the URL. The old
    `1 <= n <= 10000` cap was already OK at 10000, but the dropdown
    didn't expose it — verify both ends (validator + dropdown) agree."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin

    admin = APIAdmin.__new__(APIAdmin)
    admin.list_per_page = 50

    for n in (2000, 10_000):
        req = RequestFactory().get(f"/admin/tests/x/?per_page={n}")
        assert admin._get_effective_per_page(req, 50) == n, (
            f"per_page={n} not accepted"
        )


def test_get_effective_per_page_caps_at_50k_safety():
    """Past 50_000 the per-page selector is the wrong tool — server-side
    pagination should kick in. The validator must refuse and fall back
    to the class default (e.g. list_per_page=50), not silently 500."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin

    admin = APIAdmin.__new__(APIAdmin)
    admin.list_per_page = 50

    req = RequestFactory().get("/admin/tests/x/?per_page=100000")
    # 100000 is over the 50_000 cap → fall back to class default
    assert admin._get_effective_per_page(req, 50) == 50


def test_get_effective_per_page_rejects_zero_and_negative():
    """?per_page=0 or negative must not crash; fall back to default."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin

    admin = APIAdmin.__new__(APIAdmin)
    admin.list_per_page = 50

    for bad in ("0", "-1", "abc", ""):
        req = RequestFactory().get(f"/admin/tests/x/?per_page={bad}")
        assert admin._get_effective_per_page(req, 50) == 50


# --- Cross-page filter (Jun 2026): X-Total-Count + filter kwarg forwarding --

def test_get_api_data_reads_x_total_count_from_response():
    """`get_api_data` should read the X-Total-Count response header
    and store it on `self._api_filtered_total`. This is what tells
    the paginator the FILTERED dataset size (e.g. ?userId=1 on 100k
    rows → X-Total-Count: 10, not 100_000)."""
    from django.test import RequestFactory
    from unittest.mock import patch, MagicMock
    from django_api_factory.admin import APIAdmin

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 10
    admin.expected_total = 1000
    admin.json_to_filter = None
    # Default cache_backend is NullCacheBackend (returns None on get),
    # so cache is effectively disabled. Just make sure the changelist
    # and detail cache are also off (they're False by default).
    admin.multi_value_separator = "、"
    admin.request_timeout = 5
    # If the test framework set cache_backend_class to Redis, force
    # the null backend so we don't hit Redis during this unit test.
    admin.cache_backend_class = None  # type: ignore[assignment]

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.content = b'[{"id": 1, "userId": 1, "title": "t", "body": "b"}]'
    fake_response.headers = {"X-Total-Count": "10"}

    with patch("django_api_factory.admin.requests.get", return_value=fake_response):
        req = RequestFactory().get("/admin/tests/pagedpost/?userId=1&p=1")
        admin.get_api_data(req)

    # The header should have been captured
    assert getattr(admin, "_api_filtered_total", None) == 10, (
        f"X-Total-Count not captured; got {getattr(admin, '_api_filtered_total', None)}"
    )


def test_get_paginator_prefers_api_filtered_total_over_expected_total():
    """When the API returns X-Total-Count, the paginator should use
    that (the FILTERED size), NOT expected_total (the unfiltered
    dataset size). Otherwise the paginator would still show 2000
    pages for a 10-row filter on 100k rows."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django_api_factory.queryset import MyQuerySet

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 100_000  # unfiltered total
    # Simulate the API just returned X-Total-Count: 10
    admin._api_filtered_total = 10

    qs = MyQuerySet(model=PagedPost)
    qs._result_cache = [f"row-{i}" for i in range(10)]

    req = RequestFactory().get("/admin/tests/pagedpost/?userId=1")
    p = admin.get_paginator(req, qs, 50)
    assert p.count == 10, (
        f"Paginator used {p.count} instead of 10. "
        f"expected_total=100_000 but _api_filtered_total should win."
    )


def test_get_paginator_falls_back_to_expected_total_without_header():
    """If the API doesn't return X-Total-Count (older / custom APIs),
    fall back to expected_total (the unfiltered size declared on the
    class). This is the pre-Jun-2026 behavior, kept for backwards
    compat."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django_api_factory.queryset import MyQuerySet

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = PagedPost
    admin.list_per_page = 50
    admin.expected_total = 500
    # No _api_filtered_total set

    qs = MyQuerySet(model=PagedPost)
    qs._result_cache = [f"row-{i}" for i in range(50)]

    req = RequestFactory().get("/admin/tests/pagedpost/")
    p = admin.get_paginator(req, qs, 50)
    assert p.count == 500


def test_post_urls_forwards_filter_kwargs():
    """Post.urls() must forward filter kwargs (e.g. userId, title) as
    query params so JSONPlaceholder applies them server-side. Without
    this, the admin can only client-side filter the current page."""
    # Use a model that mirrors Post's urls() signature (we can't import
    # example.models here — conftest doesn't include the example app).
    from django_api_factory.admin import APIAdmin

    class TestPost(APIAdmin.model if False else object):
        """Stub with the same urls() pattern as example.api.models.Post."""
        @classmethod
        def urls(cls, page=1, page_size=50, **kwargs):
            from urllib.parse import quote
            qs_parts = [f"_page={page}", f"_limit={page_size}"]
            for k, v in kwargs.items():
                if v is None or v == "":
                    continue
                qs_parts.append(f"{k}={quote(str(v), safe='')}")
            return "https://jsonplaceholder.typicode.com/posts?" + "&".join(qs_parts)

    url = TestPost.urls(page=1, page_size=10, userId="1", title="foo")
    assert "userId=1" in url, f"userId not forwarded: {url}"
    assert "title=foo" in url, f"title not forwarded: {url}"
    assert "_page=1" in url
    assert "_limit=10" in url


def test_bigpost_urls_forwards_filter_kwargs():
    """BigPost.urls() same as Post — forward filter kwargs to mock server
    which now supports server-side filter (X-Total-Count returned)."""
    class TestBigPost:
        @classmethod
        def urls(cls, page=1, page_size=50, **kwargs):
            from urllib.parse import quote
            qs_parts = [f"_page={page}", f"_limit={page_size}"]
            for k, v in kwargs.items():
                if v is None or v == "":
                    continue
                qs_parts.append(f"{k}={quote(str(v), safe='')}")
            return "http://127.0.0.1:8200/posts?" + "&".join(qs_parts)

    url = TestBigPost.urls(page=2, page_size=50, userId="99", title="qui est esse")
    assert "userId=99" in url
    assert "title=qui+est+esse" in url or "title=qui%20est%20esse" in url
    assert "_page=2" in url
    assert "_limit=50" in url


# --- AJAX distinct endpoint (Jun 2026) -------------------------------------
#
# The filter UI's load-more button + debounced search box AJAX the
# changelist view with `?ajax_distinct=1&field=X&q=...&offset=N`.
# The admin's `changelist_view` short-circuits and returns JSON.

def test_changelist_view_returns_json_when_ajax_distinct():
    """`?ajax_distinct=1` in the URL → changelist_view returns a
    JSONResponse with {values, count, truncated} instead of HTML.
    The hook calls `self.get_filter_choices()` (generic) which the
    subclass can implement (server-side /distinct, or default
    in-memory walk). The AJAX endpoint just serializes the result.
    """
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django.http import JsonResponse
    from django.db import models

    class _AjaxPost(models.Model):
        app_label = "tests"
        class Meta:
            app_label = "tests"

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = _AjaxPost
    admin.request_timeout = 5
    admin.filter_distinct_limit = 200
    # Stub get_filter_choices to return a known payload (mirrors what
    # BigPostAdmin's /distinct override would return).
    def fake_get_filter_choices(field_name, request, q="", offset=0, limit=200):
        return {"field": "userId", "count": 10000, "returned": 5,
                "truncated": True, "values": [1, 2, 3, 4, 5]}
    admin.get_filter_choices = fake_get_filter_choices
    req = RequestFactory().get(
        "/admin/api/_ajaxpost/?ajax_distinct=1&field=userId&limit=5"
    )
    import json as _json
    resp = admin._ajax_distinct(req)
    assert isinstance(resp, JsonResponse)
    payload = _json.loads(resp.content)
    assert payload["count"] == 10000
    assert payload["values"] == [1, 2, 3, 4, 5]
    assert payload["truncated"] is True


def test_changelist_view_ajax_distinct_propagates_q_to_filter_choices():
    """The `?q=foo` term is forwarded to `get_filter_choices` so
    the search box's typed term actually filters the distinct set
    (server-side search, not client-side hide/show)."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django.db import models

    class _Stub(models.Model):
        app_label = "tests"
        class Meta:
            app_label = "tests"

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = _Stub
    admin.request_timeout = 5
    captured_kwargs = {}
    def fake_get_filter_choices(field_name, request, q="", offset=0, limit=200):
        captured_kwargs["q"] = q
        captured_kwargs["offset"] = offset
        captured_kwargs["limit"] = limit
        return {"values": ["x"], "count": 1, "truncated": False}
    admin.get_filter_choices = fake_get_filter_choices
    req = RequestFactory().get(
        "/admin/api/_stub/?ajax_distinct=1&field=userId&q=7777&offset=20&limit=50"
    )
    admin._ajax_distinct(req)
    assert captured_kwargs["q"] == "7777", (
        f"q param not forwarded: {captured_kwargs}"
    )
    assert captured_kwargs["offset"] == 20
    assert captured_kwargs["limit"] == 50


def test_apifilter_exposes_total_count_for_template():
    """APIFilter.__init__ sets self.total_count (and self._total_count)
    so the filter template can read {{ spec.total_count }} to populate
    the load-more button's data-total attribute. Django's template
    parser blocks attributes starting with `_` (raises
    TemplateSyntaxError) so the readable alias is mandatory.
    """
    from django.test import RequestFactory
    from django_api_factory.filter import APIFilter
    from django_api_factory.admin import APIAdmin
    from django_api_factory.models import APIModel
    from django_api_factory.mixins import schema_registry

    class _TT(APIModel):
        app_label = "tests"
        @classmethod
        def urls(cls, **kw): return "https://example.com"
        @classmethod
        def cache(cls, **kw): return None
        class Meta: app_label = "tests"

    schema_registry.register(_TT, ["category"])
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = _TT
    admin.empty_value_display = "-"
    admin.get_filter_choices = lambda field_name, request: {
        "values": ["a", "b", "c"], "count": 10_000, "truncated": True,
    }
    field = _TT._meta.get_field("category")
    req = RequestFactory().get("/admin/tests/tt/")
    f = APIFilter(field, req, {}, _TT, admin, "category")
    # The template-readable attribute is `total_count` (no underscore)
    assert f.total_count == 10_000
    # The internal alias is `_total_count` (kept for any code that
    # already reads it)
    assert f._total_count == 10_000

# Reuse the FilterItem fixture from test_filter.py for the
# APIFilter attribute test above.
try:
    from tests.test_filter import FilterItem
except Exception:
    pass


# --- Generic get_filter_choices default impl (Jun 2026) ----------------
#
# When a subclass doesn't override get_filter_choices, the default
# impl in APIAdmin walks all pages of the API, aggregates distinct
# values, caches in Redis, and serves search/load-more from cache.
# This is the path Post (and any other small/medium admin) takes
# when no server-side /distinct endpoint is available.

def test_default_get_filter_choices_returns_none_when_too_large():
    """When expected_total > filter_distinct_max_rows (default
    1000), the default impl returns None instead of trying to
    walk 2000+ pages. Subclasses (BigPostAdmin) override with
    a server-side /distinct endpoint for huge datasets.
    """
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django.db import models

    class DistinctTestModel(models.Model):
        userId = models.IntegerField()
        class Meta:
            app_label = "tests"

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = DistinctTestModel
    admin.expected_total = 100_000  # > max_rows=1000
    admin.filter_distinct_max_rows = 1000
    admin.filter_distinct_cache_ttl = 0
    req = RequestFactory().get("/admin/tests/testmodel/")
    # Returns None — let the caller fall back to per-page distinct
    result = admin.get_filter_choices("userId", req)
    assert result is None


def test_default_get_filter_choices_signature_accepts_q_offset_limit():
    """The new signature (q='', offset=0, limit=200) is what the
    AJAX endpoint uses; subclasses that override must accept it
    (BigPostAdmin does). Old call sites that pass just (field, req)
    should still work via Python kwargs (the defaults are the
    "no search, no offset, default limit" case)."""
    from django.test import RequestFactory
    from django_api_factory.admin import APIAdmin
    from django.db import models

    class DistinctTestModel(models.Model):
        userId = models.IntegerField()
        class Meta:
            app_label = "tests"

    admin = APIAdmin.__new__(APIAdmin)
    admin.model = DistinctTestModel
    admin.expected_total = 10
    admin.filter_distinct_max_rows = 1000
    admin.filter_distinct_cache_ttl = 0
    admin.request_timeout = 5
    admin.list_per_page = 10
    # Stub get_api_urls to avoid needing a model.urls() method
    from unittest.mock import patch, MagicMock
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = [
        {"userId": 1}, {"userId": 2}, {"userId": 1},  # 3 items, 2 distinct
    ]
    req = RequestFactory().get("/admin/tests/testmodel/")
    with patch.object(admin, "get_api_urls", return_value="http://mock/api"):
        with patch("django_api_factory.admin.requests.get", return_value=fake_resp):
            # No q/offset/limit → returns all distinct (3 items → 2 distinct)
            result = admin.get_filter_choices("userId", req)
    assert result is not None
    assert result["values"] == [1, 2]
    assert result["count"] == 2
    # With q="1" → only 1 (2 doesn't contain "1")
    req2 = RequestFactory().get("/admin/tests/testmodel/?q=1")
    with patch.object(admin, "get_api_urls", return_value="http://mock/api"):
        with patch("django_api_factory.admin.requests.get", return_value=fake_resp):
            result_q = admin.get_filter_choices("userId", req2, q="1")
    assert result_q["values"] == [1]
