"""Tests for APIFilter (filter.py)."""

from django.test import RequestFactory, override_settings
from django.template import Context, Template

from django_api_factory.admin import APIAdmin
from django_api_factory.filter import APIFilter, APIMultiSelectFilter
from django_api_factory.models import APIModel
from django_api_factory.mixins import schema_registry


# --- Test fixtures --------------------------------------------------------

class FilterItem(APIModel):
    app_label = "tests"

    @classmethod
    def urls(cls, **kwargs):
        return "https://example.com"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta:
        app_label = "tests"


def _make_filter(json_to_filter, params=None, filter_class=APIFilter):
    """
    Build a working APIFilter instance. The parent class
    (`AllValuesFieldListFilter.__init__`) tries to query the database
    in its __init__; APIFilter catches the resulting OperationalError
    (no Django table for APIModel) and falls back to manual init.
    """
    schema_registry.register(FilterItem, ["category"])
    admin = APIAdmin.__new__(APIAdmin)
    admin.model = FilterItem
    admin.json_to_filter = json_to_filter
    admin.empty_value_display = "-"
    request = RequestFactory().get("/admin/tests/filteritem/")
    f = filter_class(
        FilterItem._meta.get_field("category"),
        request, params or {}, FilterItem, admin, "category"
    )
    return f, admin, request


# --- Tests ----------------------------------------------------------------

def test_filter_deduplicates_choices():
    """APIFilter collects unique values from json_to_filter, dedupes duplicates."""
    f, _, _ = _make_filter([
        {"category": "apple"},
        {"category": "banana"},
        {"category": "apple"},
    ])
    # `lookup_choices` is a list of RAW VALUES (not (value, value) tuples)
    # — `AllValuesFieldListFilter.choices()` iterates `for val in ...` and
    # does `val = str(val)`. Tuples render as the Python repr "(x, x)" and
    # become unparseable in the URL.
    assert "apple" in f.lookup_choices
    assert "banana" in f.lookup_choices
    assert len(f.lookup_choices) == 2


def test_filter_choices_support_simpleui_option_indices():
    """SimpleUI reads lookup choices as option.0 and option.1."""
    f, _, _ = _make_filter([{"category": "apple"}])
    choice = f.lookup_choices[0]

    assert str(choice) == "apple"
    assert choice[0] == "apple"
    assert choice[1] == "apple"
    assert (
        Template("{{ choice.0 }}|{{ choice.1 }}")
        .render(Context({"choice": choice}))
    ) == "apple|apple"


def test_filter_splits_configured_multi_value_separator():
    """Values containing the configured separator are split + deduped."""
    sep = "\u3001"
    f, _, _ = _make_filter([
        {"category": f"apple{sep}banana"},
        {"category": f"banana{sep}apple"},  # same set, different order
    ])
    # Both rows collapse to the same sorted representation.
    assert f"apple{sep}banana" in f.lookup_choices
    assert len(f.lookup_choices) == 1


def test_filter_setup_lookup_kwargs():
    """The filter exposes lookup_kwarg / lookup_kwarg_isnull for URL building."""
    f, _, _ = _make_filter([{"category": "apple"}])
    assert f.lookup_kwarg == "category"
    assert f.lookup_kwarg_isnull == "category__isnull"


def test_filter_reads_lookup_val_from_params():
    """If `?category=apple` is in the URL, lookup_val picks it up."""
    f, _, _ = _make_filter([{"category": "apple"}], params={"category": "apple"})
    assert f.lookup_val == "apple"


def test_filter_choice_links_drop_page_param():
    """Changing a filter must reset pagination.

    Keeping `?p=N` makes server-side pagination ask the API for page N of
    the filtered dataset, which is often empty when the filter result is
    only one page.
    """
    from django.http import QueryDict

    f, _, _ = _make_filter([{"category": "banana"}])

    class FakeChangeList:
        add_facets = False

        def get_query_string(self, new_params=None, remove=None):
            query = QueryDict("p=9&per_page=25&category=apple", mutable=True)
            for key in remove or []:
                query.pop(key, None)
            for key, value in (new_params or {}).items():
                query[key] = value
            return "?" + query.urlencode()

    choices = list(f.choices(FakeChangeList()))

    assert choices
    assert all("p=" not in choice["query_string"] for choice in choices)
    assert any(
        "category=banana" in choice["query_string"]
        for choice in choices
    )


def test_filter_all_link_is_not_empty_when_it_clears_last_param():
    """`href=""` keeps the browser on the current filtered URL.

    When "All" removes the last query param, render `?` so the browser
    navigates to the same path with an empty query string.
    """
    from django.http import QueryDict

    f, _, _ = _make_filter([{"category": "banana"}], params={"category": "apple"})

    class FakeChangeList:
        add_facets = False

        def get_query_string(self, new_params=None, remove=None):
            query = QueryDict("p=9&category=apple", mutable=True)
            for key in remove or []:
                query.pop(key, None)
            for key, value in (new_params or {}).items():
                query[key] = value
            encoded = query.urlencode()
            return f"?{encoded}" if encoded else ""

    all_choice = list(f.choices(FakeChangeList()))[0]

    assert all_choice["display"] == "All"
    assert all_choice["query_string"] == "?"


def test_multi_filter_choices_skip_all_and_restore_multiple_selected_values():
    """Multi-select choices are inert options, not immediate filter links."""
    from django.http import QueryDict

    f, _, _ = _make_filter(
        [{"category": "apple"}, {"category": "banana"}, {"category": "pear"}],
        params={"category": ["apple,banana"]},
        filter_class=APIMultiSelectFilter,
    )

    class FakeChangeList:
        add_facets = False

        def get_query_string(self, new_params=None, remove=None):
            query = QueryDict("p=9&category=apple,banana", mutable=True)
            for key in remove or []:
                query.pop(key, None)
            for key, value in (new_params or {}).items():
                query[key] = value
            return "?" + query.urlencode()

    choices = list(f.choices(FakeChangeList()))

    assert [choice["display"] for choice in choices] == ["apple", "banana", "pear"]
    assert [choice["value"] for choice in choices] == ["apple", "banana", "pear"]
    assert {
        choice["value"]
        for choice in choices
        if choice["selected"]
    } == {"apple", "banana"}


def test_multi_filter_trigger_collapses_selected_values():
    """ElementUI-style trigger shows first tags plus +N overflow."""
    f, _, _ = _make_filter(
        [{"category": "apple"}],
        params={"category": ["apple,banana,pear,peach,grape,melon,mango,orange"]},
        filter_class=APIMultiSelectFilter,
    )

    assert f.selected_values == [
        "apple", "banana", "pear", "peach", "grape", "melon", "mango", "orange",
    ]
    assert f.selected_preview_values == ["apple", "banana"]
    assert f.selected_overflow_count == 6


def test_apiadmin_auto_generated_filters_are_multi_select():
    """Auto-generated API filters should use pick-many-then-apply UX."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.list_filter = []
    admin.api_list = ["category", "status"]

    filters = list(admin.get_list_filter(RequestFactory().get("/admin/")))

    assert filters == [
        ("category", APIMultiSelectFilter),
        ("status", APIMultiSelectFilter),
    ]
    assert admin.api_list == ["category", "status"]


def test_apiadmin_auto_generated_filters_support_exclude_list():
    """Default is all API fields; users can exclude noisy columns."""
    admin = APIAdmin.__new__(APIAdmin)
    admin.list_filter = []
    admin.list_filter_exclude = ["image", "password"]
    admin.api_list = ["category", "image", "status", "password"]

    filters = list(admin.get_list_filter(RequestFactory().get("/admin/")))

    assert filters == [
        ("category", APIMultiSelectFilter),
        ("status", APIMultiSelectFilter),
    ]


@override_settings(INSTALLED_APPS=["simpleui", "django.contrib.admin"])
def test_apiadmin_uses_simpleui_filters_when_theme_precedes_admin():
    """SimpleUI must be before django.contrib.admin to own admin templates."""
    admin = APIAdmin.__new__(APIAdmin)

    assert admin.use_simpleui_filters is True
    assert admin.use_elementui_filters is True
    assert admin.load_elementui_assets is False


@override_settings(INSTALLED_APPS=["django.contrib.admin", "simpleui"])
def test_apiadmin_does_not_use_simpleui_filters_after_admin():
    """Django resolves admin templates before later-installed SimpleUI."""
    admin = APIAdmin.__new__(APIAdmin)

    assert admin.use_simpleui_filters is False
    assert admin.use_elementui_filters is True
    assert admin.load_elementui_assets is True


@override_settings(
    INSTALLED_APPS=["django.contrib.admin"],
    DJANGO_API_FACTORY_ELEMENTUI_FILTERS=False,
)
def test_apiadmin_can_disable_elementui_filters():
    """Projects can opt back into the built-in non-ElementUI filter UI."""
    admin = APIAdmin.__new__(APIAdmin)

    assert admin.use_elementui_filters is False
    assert admin.load_elementui_assets is False


@override_settings(
    DJANGO_API_FACTORY_VUE_JS_URL="/static/vendor/vue.js",
    DJANGO_API_FACTORY_ELEMENTUI_JS_URL="/static/vendor/element.js",
    DJANGO_API_FACTORY_ELEMENTUI_CSS_URL="/static/vendor/element.css",
)
def test_apiadmin_elementui_asset_urls_are_configurable():
    """Projects can replace CDN URLs with self-hosted static files."""
    admin = APIAdmin.__new__(APIAdmin)

    assert admin.vue_js_url == "/static/vendor/vue.js"
    assert admin.elementui_js_url == "/static/vendor/element.js"
    assert admin.elementui_css_url == "/static/vendor/element.css"


def test_filter_empty_value_display():
    """The filter uses the admin's get_empty_value_display()."""
    f, _, _ = _make_filter([{"category": "apple"}])
    assert f.empty_value_display == "-"


def test_filter_skips_django_internal_get_params():
    """Django admin's internal params (`_changelist_filters`,
    `_selected_action`) must not be treated as data filter fields.
    Treating `_changelist_filters` as a field silently zeroes the
    result list (items don't have a `_changelist_filters` key) →
    detail views show "doesn't exist" and bounce to home."""
    # 5 items with `category` field (the registered test field)
    items = [{"category": "a"}, {"category": "b"}, {"category": "c"},
            {"category": "d"}, {"category": "e"}]
    f, admin, _ = _make_filter(items, params={
        "_changelist_filters": "p=4",
        "_selected_action": "5",
    })
    # Filter skipped these params → 5 unique choices collected.
    assert len(f.lookup_choices) == 5


# --- Cross-page filter distinct (Jun 2026) --------------------------------
#
# T1.6 dropdown was populated from json_to_filter (the current API
# page), so on 100k rows / 200 per page the userId dropdown showed
# 200 values. Jun 2026 adds APIAdmin.get_filter_choices() so subclasses
# can fetch the FULL enum (via /distinct) and the dropdown shows
# all 10_000 userIds.

def test_apifilter_uses_admin_get_filter_choices_when_provided():
    """APIFilter uses admin.get_filter_choices() (the new hook) INSTEAD
    OF json_to_filter when it's defined and returns a non-empty list.
    This is the cross-page distinct path: dropdown shows 10_000 userIds
    even though the current API page only has 3."""
    full_userids = list(range(1, 10001))
    def fake_get_filter_choices(field_name, request):
        return full_userids
    json_to_filter = [{"category": 1}, {"category": 2}, {"category": 3}]
    f, admin, _ = _make_filter(json_to_filter)
    admin.get_filter_choices = fake_get_filter_choices
    # The filter was built BEFORE get_filter_choices was set; rebuild
    # it now that the hook is in place.
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert len(f.lookup_choices) == 10000, (
        f"Filter should show all 10_000 values from get_filter_choices, "
        f"got {len(f.lookup_choices)} (legacy per-page in use)"
    )
    assert 1 in f.lookup_choices
    assert 5000 in f.lookup_choices
    assert 10000 in f.lookup_choices


def test_apifilter_falls_back_to_json_to_filter_when_no_hook():
    """No get_filter_choices on admin → use legacy per-page distinct."""
    json_to_filter = [{"category": 1}, {"category": 2}, {"category": 2},
                     {"category": 3}, {"category": 3}, {"category": 3}]
    f, _, _ = _make_filter(json_to_filter)
    # No get_filter_choices attr — must use legacy path
    assert sorted(f.lookup_choices) == [1, 2, 3]


def test_apifilter_falls_back_when_get_filter_choices_returns_none():
    """get_filter_choices defined but returns None → fall back to per-page."""
    json_to_filter = [{"category": 1}, {"category": 2}, {"category": 3}]
    f, admin, _ = _make_filter(json_to_filter)
    admin.get_filter_choices = lambda field_name, request: None
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert sorted(f.lookup_choices) == [1, 2, 3]


def test_apifilter_falls_back_when_get_filter_choices_raises():
    """get_filter_choices raises (e.g. /distinct endpoint down) →
    fall back to per-page distinct instead of crashing changelist."""
    json_to_filter = [{"category": 1}, {"category": 2}]
    f, admin, _ = _make_filter(json_to_filter)
    def boom(field_name, request):
        raise RuntimeError("mock /distinct is down")
    admin.get_filter_choices = boom
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    # Exception swallowed; per-page {1, 2} used
    assert sorted(f.lookup_choices) == [1, 2]


def test_apiadmin_default_get_filter_choices_returns_none():
    """APIAdmin.get_filter_choices default is None — subclasses opt in
    by overriding. Keeps Post / Coin / etc. working without changes."""
    from django.test import RequestFactory
    admin = APIAdmin.__new__(APIAdmin)
    req = RequestFactory().get("/admin/")
    assert admin.get_filter_choices("userId", req) is None


# --- Distinct cap + true-total title badge (Jun 2026) ---------------------
#
# After M2 cross-page distinct, the dropdown was rendering 10_000
# userIds / 100_000 titles into 41MB of HTML. The fix: cap distinct
# to 200 (configurable) and show the TRUE total count in the idle title.

def test_apifilter_title_shows_true_total_when_truncated():
    """When get_filter_choices returns {"values": [...200...], "count":
    10_000, "truncated": True}, the idle filter's title must show the
    true total only, not "200 of 10000"."""
    f, admin, _ = _make_filter([])
    admin.get_filter_choices = lambda field_name, request: {
        "values": list(range(200)),
        "count": 10_000,
        "truncated": True,
    }
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert f.title == "category (10000)", f"Got {f.title!r}"
    assert len(f.lookup_choices) == 200


def test_apifilter_title_omits_count_when_selected():
    """Selected filters show value tags, so the count badge is hidden."""
    f, admin, _ = _make_filter([])
    admin.get_filter_choices = lambda field_name, request: {
        "values": list(range(200)),
        "count": 10_000,
        "truncated": True,
    }
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {"category": ["1,2"]}, FilterItem, admin, "category",
    )
    assert f.title == "category", f"Got {f.title!r}"


def test_apifilter_title_shows_just_count_when_not_truncated():
    """When get_filter_choices returns all 10 values (no truncation),
    title shows the simple "(10)" badge. Used when the dataset is
    small or the admin didn't cap."""
    f, admin, _ = _make_filter([])
    admin.get_filter_choices = lambda field_name, request: {
        "values": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        "count": 10,
        "truncated": False,
    }
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert f.title == "category (10)", f"Got {f.title!r}"


def test_apifilter_title_omits_count_when_empty():
    """No choices at all → just the field name, no count badge."""
    f, admin, _ = _make_filter([])
    admin.get_filter_choices = lambda field_name, request: {"values": [], "count": 0}
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert f.title == "category", f"Got {f.title!r}"


def test_apifilter_legacy_list_return_works_without_count():
    """Backwards compat: get_filter_choices returning a plain list
    (old T1.6 interface) still works. Title gets a simple "(N)"
    badge, no "of" suffix."""
    f, admin, _ = _make_filter([])
    admin.get_filter_choices = lambda field_name, request: ["x", "y", "z"]
    f = APIFilter(
        FilterItem._meta.get_field("category"),
        RequestFactory().get("/admin/tests/filteritem/"),
        {}, FilterItem, admin, "category",
    )
    assert f.title == "category (3)", f"Got {f.title!r}"
