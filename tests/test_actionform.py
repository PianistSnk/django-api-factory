"""Tests for ActionFormMixin — generic modal-form + ajax-submit, no simpleui."""

import json
import pytest
from unittest.mock import MagicMock
from django.contrib import admin as django_admin
from django.contrib.admin import AdminSite
from django.test import RequestFactory

from django_api_factory.models import APIModel
from django_api_factory.mixins import ActionFormMixin


# --- Test fixtures: a model + admin with a .layer action ------------------

class Widget(APIModel):
    app_label = "tests"

    def urls(self, **kwargs):
        return "https://example.com"

    def cache(self, **kwargs):
        return None

    class Meta:
        app_label = "tests"


@pytest.fixture
def admin_with_action():
    """Build an ActionFormMixin admin with one .layer action, registered on Widget."""
    received = {}

    class TestAdmin(ActionFormMixin, django_admin.ModelAdmin):
        actions = ["add_remarks"]
        list_per_page = 50

        def get_queryset(self, request):
            return []

        def add_remarks(self, request, queryset):
            received["remarks"] = request.POST.get("remarks", "")
            received["status"] = request.POST.get("status", "")
            received["selected_count"] = len(list(queryset))
            return None

        add_remarks.layer = {
            "params": [
                {
                    "type": "input",
                    "key": "remarks",
                    "label": "Remarks",
                    "require": False,
                },
                {
                    "type": "radio",
                    "key": "status",
                    "label": "Status",
                    "options": [
                        {"key": "yes", "label": "Yes"},
                        {"key": "no", "label": "No"},
                    ],
                },
            ]
        }

    site = AdminSite()
    admin_inst = TestAdmin(Widget, site)
    admin_inst._received = received
    return admin_inst


# --- Tests ----------------------------------------------------------------

def test_action_form_view_returns_layer_schema(admin_with_action):
    """GET action-form/<name>/ returns the .layer schema as JSON."""
    factory = RequestFactory()
    request = factory.get("/admin/tests/widget/action-form/add_remarks/")
    response = admin_with_action.action_form_view(request, "add_remarks")
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["action_name"] == "add_remarks"
    assert data["title"] == "Add remarks"  # Django auto-humanizes the action name
    assert len(data["params"]) == 2
    assert data["params"][0]["key"] == "remarks"
    assert data["params"][1]["key"] == "status"


def test_action_form_view_uses_layer_title_if_present():
    """If .layer has a 'title', use that instead of the action name."""

    class InnerAdmin(ActionFormMixin, django_admin.ModelAdmin):
        def get_queryset(self, request):
            return []

        def do_something(self, request, queryset):
            return None

        do_something.layer = {
            "title": "Custom Title",
            "params": [{"type": "input", "key": "x", "label": "X"}],
        }

    site = AdminSite()
    admin_inst = InnerAdmin(Widget, site)
    factory = RequestFactory()
    request = factory.get("/admin/tests/widget/action-form/do_something/")
    response = admin_inst.action_form_view(request, "do_something")
    data = json.loads(response.content)
    assert data["title"] == "Custom Title"


def test_action_form_view_404_for_unknown_action(admin_with_action):
    """GET action-form/<unknown>/ returns 404."""
    factory = RequestFactory()
    request = factory.get("/admin/tests/widget/action-form/does_not_exist/")
    response = admin_with_action.action_form_view(request, "does_not_exist")
    assert response.status_code == 404
    data = json.loads(response.content)
    assert data["status"] == "error"


def test_action_submit_view_405_on_get(admin_with_action):
    """GET to action-submit returns 405 (POST required)."""
    factory = RequestFactory()
    request = factory.get("/admin/tests/widget/action-submit/add_remarks/")
    response = admin_with_action.action_submit_view(request, "add_remarks")
    assert response.status_code == 405


def test_action_submit_view_executes_action_with_post_data(admin_with_action):
    """POST action-submit/<name>/ runs the action and returns JSON."""
    factory = RequestFactory()
    request = factory.post(
        "/admin/tests/widget/action-submit/add_remarks/",
        data={"remarks": "hello world", "status": "yes"},
    )
    response = admin_with_action.action_submit_view(request, "add_remarks")
    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["status"] == "success"
    # Verify the action actually received the POST data
    assert admin_with_action._received["remarks"] == "hello world"
    assert admin_with_action._received["status"] == "yes"


def test_action_submit_view_404_for_unknown_action(admin_with_action):
    """POST to unknown action returns 404."""
    factory = RequestFactory()
    request = factory.post("/admin/tests/widget/action-submit/does_not_exist/", data={})
    response = admin_with_action.action_submit_view(request, "does_not_exist")
    assert response.status_code == 404


def test_action_submit_view_handles_action_returning_dict(admin_with_action):
    """If action returns a dict, it's returned as JSON."""

    class DictAdmin(ActionFormMixin, django_admin.ModelAdmin):
        def get_queryset(self, request):
            return []

        def custom_action(self, request, queryset):
            return {"status": "redirect", "url": "/somewhere/", "msg": "ok"}

    site = AdminSite()
    admin_inst = DictAdmin(Widget, site)
    factory = RequestFactory()
    request = factory.post("/admin/tests/widget/action-submit/custom_action/", data={})
    response = admin_inst.action_submit_view(request, "custom_action")
    data = json.loads(response.content)
    assert data["status"] == "redirect"
    assert data["url"] == "/somewhere/"


def test_action_submit_view_passes_none_when_action_returns_none(admin_with_action):
    """If action returns None, response is {'status': 'success', 'msg': 'Success!'}."""
    factory = RequestFactory()
    request = factory.post(
        "/admin/tests/widget/action-submit/add_remarks/", data={"remarks": "x"}
    )
    response = admin_with_action.action_submit_view(request, "add_remarks")
    data = json.loads(response.content)
    assert data == {"status": "success", "msg": "Success!"}



def test_action_form_view_simpleui_style_with_width():
    """simpleui-style layer: width, icon, type, style in the response."""
    class InnerAdmin(ActionFormMixin, django_admin.ModelAdmin):
        def get_queryset(self, request):
            return MagicMock()

        def supplement_remarks(self, request, queryset):
            return None

        supplement_remarks.icon = "fas fa-download"
        supplement_remarks.type = "info"
        supplement_remarks.style = "color:white"
        supplement_remarks.layer = {
            "title": "Add/update remarks",
            "width": "40%",
            "params": [
                {
                    "type": "input",
                    "key": "remarks",
                    "label": "Add/update remarks",
                    "require": True,
                }
            ],
        }

    admin = InnerAdmin.__new__(InnerAdmin)
    factory = RequestFactory()
    request = factory.get("/admin/tests/widget/action-form/supplement_remarks/")
    response = admin.action_form_view(request, "supplement_remarks")
    data = json.loads(response.content)
    assert data["title"] == "Add/update remarks"
    assert data["width"] == "40%"
    assert data["params"][0]["key"] == "remarks"
    assert data["params"][0]["require"] is True
    assert data["icon"] == "fas fa-download"
    assert data["type"] == "info"
    assert data["style"] == "color:white"
