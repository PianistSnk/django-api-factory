"""Tests for APIModel.parse_response — 4 industry-standard envelope shapes.

We support (in priority order, first match wins):
1. Bare list              [{...}, {...}]            (REST canonical)
2. {"data": [...]}        (custom APIs / Laravel)
3. {"items": [...]}       (older internal APIs)
4. {"results": [...]}     (DRF PageNumberPagination default)

Anything else raises ValueError with a developer-actionable message.

These tests don't spin up a full admin — they exercise `parse_response`
directly on a tiny APIModel subclass to keep the unit-test scope tight.
"""

from __future__ import annotations

import pytest

from django_api_factory.models import APIModel


class _DemoModel(APIModel):
    """Minimal concrete APIModel for parse_response unit tests."""

    @classmethod
    def urls(cls, **kwargs):
        return "http://example.com/demo"

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        app_label = "tests"
        # abstract=False so we can instantiate the classmethod on it
        abstract = False


# ---------------------------------------------------------------------------
# Bare list — the REST canonical form, the recommended default.
# ---------------------------------------------------------------------------


def test_parse_response_bare_list():
    rows = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
    assert _DemoModel.parse_response(rows) is rows


def test_parse_response_empty_list():
    """Empty list is valid — admin just shows 0 results."""
    assert _DemoModel.parse_response([]) == []


# ---------------------------------------------------------------------------
# The 3 envelope shapes we recognize.
# ---------------------------------------------------------------------------


def test_parse_response_data_envelope():
    payload = {"data": [{"id": 1}], "code": 200, "msg": "ok"}
    assert _DemoModel.parse_response(payload) == [{"id": 1}]


def test_parse_response_items_envelope():
    payload = {"items": [{"id": 1}, {"id": 2}], "code": 200}
    assert _DemoModel.parse_response(payload) == [{"id": 1}, {"id": 2}]


def test_parse_response_results_envelope():
    payload = {
        "count": 2,
        "next": None,
        "previous": None,
        "results": [{"id": 1}, {"id": 2}],
    }
    assert _DemoModel.parse_response(payload) == [{"id": 1}, {"id": 2}]


# ---------------------------------------------------------------------------
# Priority: when multiple keys are present, `data` wins.
# ---------------------------------------------------------------------------


def test_parse_response_priority_data_over_items():
    """First match wins, so `data` is preferred over `items` / `results`."""
    payload = {
        "data": [{"from": "data"}],
        "items": [{"from": "items"}],
        "results": [{"from": "results"}],
    }
    result = _DemoModel.parse_response(payload)
    assert result == [{"from": "data"}]


def test_parse_response_priority_items_over_results():
    """When `data` is absent, `items` wins over `results`."""
    payload = {
        "items": [{"from": "items"}],
        "results": [{"from": "results"}],
    }
    result = _DemoModel.parse_response(payload)
    assert result == [{"from": "items"}]


# ---------------------------------------------------------------------------
# Unknown / unsupported formats raise ValueError.
# ---------------------------------------------------------------------------


def test_parse_response_unknown_envelope_key_raises():
    """An envelope with a non-standard key (`payload`) should raise."""
    payload = {"payload": [{"id": 1}], "code": 200}
    with pytest.raises(ValueError) as exc_info:
        _DemoModel.parse_response(payload)
    msg = str(exc_info.value)
    assert "_DemoModel.parse_response" in msg
    assert "payload" in msg  # the offending key shows up in the example
    assert "override APIModel.parse_response" in msg  # actionable guidance


def test_parse_response_envelope_with_non_list_value_raises():
    """An envelope where the value under `data` is not a list should raise
    (not silently swallow). E.g. `{"data": null}` or `{"data": {}}`."""
    for bad in ({"data": None}, {"data": {}}, {"data": "string"}):
        with pytest.raises(ValueError):
            _DemoModel.parse_response(bad)


def test_parse_response_string_response_raises():
    """Plain string is not a recognized shape — must raise."""
    with pytest.raises(ValueError):
        _DemoModel.parse_response("not json")


def test_parse_response_none_raises():
    """None is not a recognized shape — must raise."""
    with pytest.raises(ValueError):
        _DemoModel.parse_response(None)


# ---------------------------------------------------------------------------
# Override path: subclasses can provide custom logic.
# ---------------------------------------------------------------------------


class _CustomModel(_DemoModel):
    """APIModel that overrides parse_response to unwrap a custom envelope."""

    @classmethod
    def parse_response(cls, response_data):
        if isinstance(response_data, list):
            return response_data
        # Custom logic: walk a nested envelope
        return response_data.get("payload", {}).get("rows", [])


def test_parse_response_override_custom_envelope():
    """Subclass can override to support exotic envelope shapes."""
    payload = {"payload": {"rows": [{"id": 1}, {"id": 2}]}}
    assert _CustomModel.parse_response(payload) == [{"id": 1}, {"id": 2}]


def test_parse_response_override_does_not_break_base_behavior():
    """Overriding on a subclass must not affect the base class default."""
    # Base class still rejects the exotic envelope
    with pytest.raises(ValueError):
        _DemoModel.parse_response({"payload": {"rows": [{"id": 1}]}})
    # Subclass accepts it
    assert _CustomModel.parse_response({"payload": {"rows": [{"id": 1}]}}) == [
        {"id": 1}
    ]


# ---------------------------------------------------------------------------
# Error message includes the response preview (truncated) for debuggability.
# ---------------------------------------------------------------------------


def test_parse_response_error_message_includes_preview():
    """The ValueError message includes a preview of the response, so a
    developer reading the traceback can see what the API actually returned."""
    payload = {"weird": "x" * 500}  # 503 chars, should be truncated to 200
    with pytest.raises(ValueError) as exc_info:
        _DemoModel.parse_response(payload)
    msg = str(exc_info.value)
    # Preview is truncated to 200 chars max — but the string goes through
    # `repr()` of the str()'d dict, so we just check the total x count
    # is bounded (not "201 or more") and that the offending value is
    # present in some form.
    assert "x" * 100 in msg  # at least 100 consecutive x's in the preview
    # The preview is truncated, so a long run of 500 x's is NOT in the message
    assert "x" * 250 not in msg
