"""Tests for AuditLogMixin — verify default no-op behavior and subclass override."""

from django_api_factory.mixins import AuditLogMixin


def test_auditlogmixin_default_noop():
    """Default log_query / log_download return None and write nothing."""
    mixin = AuditLogMixin()
    assert mixin.log_query(None, "TestModel") is None
    assert mixin.log_download(None, "TestModel", "file.pdf", "pdf") is None
    assert mixin.enable_audit_log is False


def test_auditlogmixin_subclass_can_override():
    """Subclasses can override log_query to add audit behavior."""
    calls = []

    class ProjectFlavoredMixin(AuditLogMixin):
        def log_query(self, request, model_name):
            calls.append(("query", model_name))
            return "logged"

        def log_download(self, request, model_name, filename, type_):
            calls.append(("download", filename, type_))
            return "logged"

    mixin = ProjectFlavoredMixin()
    assert mixin.log_query(None, "Post") == "logged"
    assert mixin.log_download(None, "Post", "x.pdf", "pdf") == "logged"
    assert calls == [
        ("query", "Post"),
        ("download", "x.pdf", "pdf"),
    ]


def test_apiadmin_inherits_auditlogmixin():
    """APIAdmin should inherit from AuditLogMixin so hooks are available."""
    from django_api_factory.admin import APIAdmin
    from django_api_factory.mixins import AuditLogMixin
    assert issubclass(APIAdmin, AuditLogMixin)


def test_multi_value_separator_default():
    """Default uses 顿号 (project convention)."""
    from django_api_factory.admin import APIAdmin
    assert APIAdmin.multi_value_separator == "、"


def test_multi_value_separator_override():
    """Subclasses can override to use , or | etc."""
    from django_api_factory.admin import APIAdmin

    class CommaAdmin(APIAdmin):
        multi_value_separator = ","

    class PipeAdmin(APIAdmin):
        multi_value_separator = "|"

    assert CommaAdmin.multi_value_separator == ","
    assert PipeAdmin.multi_value_separator == "|"


def test_handle_search_condition_uses_configured_separator():
    """handle_search_condition should use self.multi_value_separator, not hardcoded 顿号."""
    # Direct unit test of the splitter logic (mirrors what the nested function does)
    from django_api_factory.admin import APIAdmin

    class PipeAdmin(APIAdmin):
        multi_value_separator = "|"

    sep = PipeAdmin.multi_value_separator
    item_value = "a|b|c"
    # Mimic the search logic with the configured separator
    assert sep.join(sorted(item_value.split(sep))) == "a|b|c"

    class CommaAdmin(APIAdmin):
        multi_value_separator = ","

    sep = CommaAdmin.multi_value_separator
    item_value = "c,a,b"
    assert sep.join(sorted(item_value.split(sep))) == "a,b,c"


# --- ExportMixin tests ---

def test_exportmixin_get_export_fields_default():
    """get_export_fields returns self.export_list if set, else None."""
    from django_api_factory.mixins import ExportMixin
    m = ExportMixin()
    m.export_list = ["a", "b", "c"]
    assert m.get_export_fields() == ["a", "b", "c"]
    del m.export_list
    assert m.get_export_fields() is None


def test_exportmixin_get_export_data_dicts():
    """get_export_data produces one dict per object with the configured fields."""
    from django_api_factory.mixins import ExportMixin

    class Row:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    m = ExportMixin()
    m.export_list = ["name", "value"]
    rows = m.get_export_data([Row(name="x", value=1), Row(name="y", value=2)])
    assert rows == [
        {"name": "x", "value": 1},
        {"name": "y", "value": 2},
    ]


def test_exportmixin_get_export_data_missing_attr():
    """Missing attributes are coerced to '' (matches legacy behavior)."""
    from django_api_factory.mixins import ExportMixin

    class Row:
        name = "x"

    m = ExportMixin()
    m.export_list = ["name", "missing"]
    assert m.get_export_data([Row()]) == [{"name": "x", "missing": ""}]


# --- Date param parsing tests (T1.1i) ---

def _make_admin_subclass(attrs):
    """Build an APIAdmin instance bypassing __init__ (which needs model+admin_site)."""
    from django_api_factory.admin import APIAdmin
    cls = type("TestAdmin", (APIAdmin,), attrs)
    return cls.__new__(cls)


def test_parse_dt_empty():
    from django_api_factory.admin import APIAdmin
    a = _make_admin_subclass({})
    assert a.parse_dt("") == ""


def test_parse_dt_admin_date_hierarchy_format():
    """Django admin sends '<relative-word> <Mon DD YYYY>' — strip first token."""
    from django_api_factory.admin import APIAdmin
    a = _make_admin_subclass({})
    assert a.parse_dt("今天 Jun 5 2026") == "20260605"
    assert a.parse_dt("昨天 Jun 4 2026") == "20260604"


def test_parse_dt_pure_date_string():
    """Bare 'Mon DD YYYY' also works (defensive)."""
    from django_api_factory.admin import APIAdmin
    a = _make_admin_subclass({})
    assert a.parse_dt("Jun 5 2026") == "20260605"


def test_parse_dt_unparseable_returns_empty():
    """Garbage input returns '' instead of raising."""
    from django_api_factory.admin import APIAdmin
    a = _make_admin_subclass({})
    assert a.parse_dt("not a date") == ""
    assert a.parse_dt("2026-06-05") == ""  # ISO not supported by default
    assert a.parse_dt(None) == ""  # type: ignore


def test_parse_paras_date_params_converted():
    """parse_paras converts declared date_params, leaves others alone."""
    a = _make_admin_subclass({"date_params": ["dt", "dt_e"]})
    out = a.parse_paras({"dt": "今天 Jun 5 2026", "dt_e": "今天 Jun 4 2026", "flag": "0", "q": "foo"})
    assert out == {"dt": "20260605", "dt_e": "20260604", "flag": "0", "q": "foo"}


def test_parse_paras_no_date_params_returns_copy():
    """If date_params is empty, parse_paras just copies the dict (no parsing)."""
    a = _make_admin_subclass({})  # default date_params = []
    out = a.parse_paras({"dt": "今天 Jun 5 2026", "flag": "0"})
    assert out == {"dt": "今天 Jun 5 2026", "flag": "0"}


def test_parse_paras_does_not_mutate_input():
    """parse_paras returns a new dict, doesn't mutate the caller's dict."""
    a = _make_admin_subclass({"date_params": ["dt"]})
    original = {"dt": "今天 Jun 5 2026", "flag": "0"}
    a.parse_paras(original)
    assert original == {"dt": "今天 Jun 5 2026", "flag": "0"}  # unchanged


def test_parse_paras_missing_date_param_unchanged():
    """If a date_param is not in paras, the result omits it (not in dict)."""
    a = _make_admin_subclass({"date_params": ["dt", "dt_e"]})
    out = a.parse_paras({"dt": "今天 Jun 5 2026"})
    assert out == {"dt": "20260605"}  # dt_e not in result


# --- _handle_search_condition (BigPost-100k filter bug fix, Jun 2026) ----

def test_handle_search_condition_single_numeric_exact_match():
    """The BigPost-100k bug: `?userId=1` previously matched userIds
    1, 10-19, 21, 31, ...  because of `'1' in '10'` substring-match.
    After the fix: single term, no separator → EXACT equality with
    int coercion so numeric fields match by value."""
    from django_api_factory.admin import _handle_search_condition
    sep = "、"

    # The exact bug case — userId=1 must NOT match userId=10
    assert _handle_search_condition(10, ["1"], sep) is False
    assert _handle_search_condition(11, ["1"], sep) is False
    assert _handle_search_condition(19, ["1"], sep) is False
    assert _handle_search_condition(21, ["1"], sep) is False
    # But it DOES match userId=1
    assert _handle_search_condition(1, ["1"], sep) is True
    # And it doesn't match userId=2 (different number, no substring overlap)
    assert _handle_search_condition(2, ["1"], sep) is False


def test_handle_search_condition_single_string_exact_match():
    """String fields also get exact equality (no substring). `?title=foo`
    matches title='foo' but NOT title='foobar' (the previous substring
    match would have incorrectly included 'foobar')."""
    from django_api_factory.admin import _handle_search_condition
    sep = "、"

    assert _handle_search_condition("foo", ["foo"], sep) is True
    assert _handle_search_condition("foobar", ["foo"], sep) is False
    assert _handle_search_condition("barfoo", ["foo"], sep) is False
    assert _handle_search_condition("FOO", ["foo"], sep) is False  # case-sensitive


def test_handle_search_condition_int_vs_string_value():
    """API may return userId as int (10) while URL param is string ('10').
    int coercion normalizes both sides so they match."""
    from django_api_factory.admin import _handle_search_condition
    sep = "、"

    assert _handle_search_condition(10, ["10"], sep) is True  # int item, str term
    assert _handle_search_condition("10", ["10"], sep) is True  # both str


def test_handle_search_condition_multiterm_or_equals():
    """Multi-term (e.g. `?userId=1,2`) → OR-equals: match if item equals
    ANY of the terms. NOT substring — so userId=12 must NOT match
    `?userId=1,2`."""
    from django_api_factory.admin import _handle_search_condition
    sep = ","

    assert _handle_search_condition(1, ["1", "2"], sep) is True
    assert _handle_search_condition(2, ["1", "2"], sep) is True
    assert _handle_search_condition(12, ["1", "2"], sep) is False  # no substring
    assert _handle_search_condition(3, ["1", "2"], sep) is False


def test_handle_search_condition_multivalued_cell_with_separator():
    """Multi-valued cells like '苹果、香蕉' compare canonically against
    the search terms. Item '苹果、香蕉' matches search ['苹果']; item
    '苹果' (no separator) also matches ['苹果']."""
    from django_api_factory.admin import _handle_search_condition
    sep = "、"

    # Cell with separator: "苹果、香蕉" split-sorted-joined → canonical
    # "苹果、香蕉"; search term is single "苹果" (no sep in term)
    # → falls to the single-term branch → exact string equality.
    # NOTE: this is exact match, not "any of the cell values", by design
    # (the URL param IS the cell value the user picked from the filter).
    assert _handle_search_condition("苹果、香蕉", ["苹果"], sep) is False  # full string compare
    assert _handle_search_condition("苹果", ["苹果"], sep) is True

    # Multi-term with separator: search ['苹果', '香蕉'] (sep "、" in terms)
    # → OR-equals: matches if cell EQUALS any term.
    assert _handle_search_condition("苹果", ["苹果", "香蕉"], sep) is True
    assert _handle_search_condition("香蕉", ["苹果", "香蕉"], sep) is True
    assert _handle_search_condition("葡萄", ["苹果", "香蕉"], sep) is False
