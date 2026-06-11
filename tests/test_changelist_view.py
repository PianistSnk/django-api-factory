"""Tests for APIChangeList (changelist.py: get_filters_params + get_results).

APIChangeList overrides two pieces of the stock Django ChangeList:
1. get_filters_params — strips `per_page` (and other reserved params)
   so they don't get fed into qs.filter() as if they were model lookups.
2. get_results — always routes the result_list through paginator.page()
   so the `?per_page=N` override actually slices the queryset, even
   when the dataset fits on one page (which is when stock ChangeList
   short-circuits and returns _clone()).

Plus the F1 fix: clamp page_num to [1, num_pages] so out-of-range
`?p=N` doesn't 500 via the template's elided_page_range.
"""

import pytest
from unittest.mock import MagicMock, patch

from django.contrib.admin.views.main import ChangeList
from django.http import QueryDict

from django_api_factory.changelist import APIChangeList, APIADMIN_RESERVED_GET_PARAMS


# --- APIADMIN_RESERVED_GET_PARAMS ---------------------------------------

def test_reserved_params_is_per_page():
    """Only `per_page` is reserved; everything else stays in lookup_params."""
    assert APIADMIN_RESERVED_GET_PARAMS == frozenset({"per_page"})


# --- get_filters_params: strip reserved, keep rest ---------------------

def test_get_filters_params_strips_per_page():
    """The override's job is to drop reserved keys; we patch super so the
    test only exercises APIChangeList's own pop() loop (not Django stock)."""
    # .copy() makes the QueryDict mutable so pop() works inside the override.
    with patch.object(ChangeList, "get_filters_params",
                      return_value=QueryDict("per_page=50&q=foo&userId__exact=3").copy()):
        cl = APIChangeList.__new__(APIChangeList)
        cl.model_admin = MagicMock()
        result = cl.get_filters_params()
    assert "per_page" not in result
    assert result["q"] == "foo"
    assert result["userId__exact"] == "3"


def test_get_filters_params_no_per_page_no_change():
    with patch.object(ChangeList, "get_filters_params",
                      return_value=QueryDict("q=foo&userId__exact=3").copy()):
        cl = APIChangeList.__new__(APIChangeList)
        cl.model_admin = MagicMock()
        result = cl.get_filters_params()
    assert result["q"] == "foo"
    assert result["userId__exact"] == "3"


def test_get_filters_params_explicit_params_arg():
    """When `params` is passed explicitly, it's forwarded to super()."""
    explicit = QueryDict("per_page=99&q=bar").copy()
    with patch.object(ChangeList, "get_filters_params", return_value=explicit) as mock_super:
        cl = APIChangeList.__new__(APIChangeList)
        cl.model_admin = MagicMock()
        result = cl.get_filters_params(explicit)
    assert "per_page" not in result
    assert result["q"] == "bar"
    # Confirm the explicit arg was forwarded (not self.params)
    mock_super.assert_called_once_with(explicit)


# --- get_results: state setup helpers -----------------------------------

def _make_cl_for_results(*, page_num=1, show_all=False, list_per_page=10,
                         list_max_show_all=200, total=100, page_per_page=10,
                         num_pages=10, show_full_result_count=True,
                         full_result_count=None, page_raises=None):
    """Build an APIChangeList with the state get_results reads/writes.

    full_result_count defaults to `total` when not given (matching what
    stock ChangeList would have set).
    """
    cl = APIChangeList.__new__(APIChangeList)
    cl.page_num = page_num
    cl.show_all = show_all
    cl.list_per_page = list_per_page
    cl.list_max_show_all = list_max_show_all
    cl.queryset = MagicMock()
    cl.queryset._clone.return_value = "<full queryset clone>"

    paginator = MagicMock()
    paginator.per_page = page_per_page
    paginator.count = total
    paginator.num_pages = num_pages
    if page_raises is not None:
        paginator.page.side_effect = page_raises
    else:
        page_mock = MagicMock()
        page_mock.object_list = [f"row{i}" for i in range(page_per_page)]
        paginator.page.return_value = page_mock

    cl.model_admin = MagicMock()
    cl.model_admin.get_paginator.return_value = paginator
    cl.model_admin.show_full_result_count = show_full_result_count
    if full_result_count is not None:
        cl.full_result_count = full_result_count
    return cl, paginator


# --- get_results: state writes (effective_per_page, result_count) ------

def test_get_results_writes_effective_per_page():
    """paginator.per_page (post-?per_page=N) is exposed as effective_per_page."""
    cl, paginator = _make_cl_for_results(page_per_page=25)
    cl.get_results(MagicMock())  # request arg is unused in our impl
    assert cl.effective_per_page == paginator.per_page == 25
    assert cl.paginator is paginator


def test_get_results_sets_result_count_and_can_show_all():
    cl, _ = _make_cl_for_results(total=50, list_max_show_all=200)
    cl.get_results(MagicMock())
    assert cl.result_count == 50
    assert cl.can_show_all is True  # 50 <= 200


def test_get_results_can_show_all_false_when_total_exceeds_max():
    cl, _ = _make_cl_for_results(total=300, list_max_show_all=200)
    cl.get_results(MagicMock())
    assert cl.can_show_all is False


def test_get_results_multi_page_when_total_exceeds_per_page():
    cl, _ = _make_cl_for_results(total=100, page_per_page=10)
    cl.get_results(MagicMock())
    assert cl.multi_page is True


def test_get_results_not_multi_page_when_total_fits():
    cl, _ = _make_cl_for_results(total=5, page_per_page=10)
    cl.get_results(MagicMock())
    assert cl.multi_page is False


# --- get_results: F1 page_num clamp ------------------------------------

def test_get_results_clamps_page_num_to_num_pages():
    """Page beyond num_pages silently clamps to the last page (F1 fix)."""
    cl, _ = _make_cl_for_results(page_num=999, num_pages=10)
    cl.get_results(MagicMock())
    assert cl.page_num == 10


def test_get_results_clamps_page_num_to_1():
    """Page below 1 clamps to 1 (F1 fix)."""
    cl, _ = _make_cl_for_results(page_num=0, num_pages=10)
    cl.get_results(MagicMock())
    assert cl.page_num == 1


def test_get_results_skips_clamp_when_num_pages_is_zero():
    """When num_pages=0 (empty dataset), don't run min/max — leave page_num alone."""
    cl, _ = _make_cl_for_results(page_num=5, num_pages=0)
    cl.get_results(MagicMock())
    assert cl.page_num == 5


# --- get_results: show_all vs paginator path ---------------------------

def test_get_results_show_all_path_uses_clone():
    """When show_all=True AND can_show_all=True, result_list = queryset._clone().

    paginator.page() should NOT be called in this path.
    """
    cl, paginator = _make_cl_for_results(
        show_all=True, total=5, list_max_show_all=200,  # can_show_all = 5 <= 200
    )
    cl.get_results(MagicMock())
    paginator.page.assert_not_called()
    assert cl.result_list == "<full queryset clone>"


def test_get_results_normal_path_calls_paginator():
    cl, paginator = _make_cl_for_results(show_all=False, total=100, page_per_page=10)
    cl.get_results(MagicMock())
    paginator.page.assert_called_once_with(cl.page_num)
    assert len(cl.result_list) == 10


def test_get_results_paginator_page_falls_back_to_clone():
    """If paginator.page() raises, fall back to full clone (don't crash)."""
    from django.core.paginator import EmptyPage
    cl, paginator = _make_cl_for_results(
        show_all=False, total=100, page_per_page=10,
        page_raises=EmptyPage("out of range"),
    )
    cl.get_results(MagicMock())  # must not raise
    assert cl.result_list == "<full queryset clone>"


# --- get_results: show_admin_actions, full_result_count ---------------

def test_get_results_full_result_count_set_from_result_count():
    cl, _ = _make_cl_for_results(total=42)
    cl.get_results(MagicMock())
    assert cl.full_result_count == 42


def test_get_results_show_admin_actions_true_when_have_count():
    """show_admin_actions = True when show_full_result_count=True AND count>0."""
    cl, _ = _make_cl_for_results(
        total=100, show_full_result_count=True, full_result_count=100,
    )
    cl.get_results(MagicMock())
    assert cl.show_admin_actions is True


def test_get_results_show_admin_actions_false_when_count_is_zero():
    """show_admin_actions = False when full_result_count is 0 (no rows to act on)."""
    cl, _ = _make_cl_for_results(
        total=0, show_full_result_count=True, full_result_count=0,
    )
    cl.get_results(MagicMock())
    assert cl.show_admin_actions is False


def test_get_results_show_admin_actions_true_when_full_count_disabled():
    """show_admin_actions = True when show_full_result_count is False (the
    'or' branch of `not show_full_result_count or bool(...)`)."""
    cl, _ = _make_cl_for_results(
        total=0, show_full_result_count=False, full_result_count=0,
    )
    cl.get_results(MagicMock())
    assert cl.show_admin_actions is True
