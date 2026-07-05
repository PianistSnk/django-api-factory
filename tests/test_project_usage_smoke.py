"""Project-level smoke test for the documented APIAdmin usage."""

import json
from urllib.parse import parse_qs, quote, urlparse

from django.contrib.admin import AdminSite
from django.test import RequestFactory

from django_api_factory.admin import APIAdmin
from django_api_factory.models import APIModel


class ProjectSmokePost(APIModel):
    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs):
        query = [f"page={page}", f"page_size={page_size}"]
        query.extend(
            f"{key}={quote(str(value), safe='')}"
            for key, value in kwargs.items()
            if value not in (None, "")
        )
        return "https://api.example.test/posts?" + "&".join(query)

    @classmethod
    def cache(cls, **kwargs):
        return None

    class Meta(APIModel.Meta):
        app_label = "tests"


class ProjectSmokeAdmin(APIAdmin):
    list_per_page = 25
    expected_total = 42


class ProjectOrderedAdmin(APIAdmin):
    list_display = ["id", "title", "userId"]
    list_per_page = 25
    expected_total = 42


class ProjectExcludeAdmin(APIAdmin):
    api_exclude_fields = ["id", "body"]
    list_per_page = 25
    expected_total = 42


class FakeAPIResponse:
    status_code = 200

    def __init__(self, rows, total=42):
        self.headers = {"X-Total-Count": str(total)}
        self.content = json.dumps(rows).encode("utf-8")


class ProjectSmokeUser:
    pk = 1
    is_active = True
    is_staff = True
    is_superuser = True

    def has_perm(self, *args, **kwargs):
        return True


def test_project_can_load_api_data_through_admin(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get(
        "/admin/tests/projectsmokepost/",
        {"p": "2", "per_page": "25", "userId": "7"},
    )
    request.user = ProjectSmokeUser()

    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeAPIResponse(
            [
                {"id": 101, "userId": 7, "title": "First API row", "body": "alpha"},
                {"id": 102, "userId": 7, "title": "Second API row", "body": "beta"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, fields = admin.get_api_data(request)
    rows = list(queryset)

    assert fields == ["userId", "title", "body"]
    assert [row.id for row in rows] == [101, 102]
    assert rows[0].title == "First API row"
    assert getattr(admin, "_api_filtered_total") == 42
    assert len(calls) == 1
    called_url, timeout = calls[0]
    parsed_url = urlparse(called_url)
    assert timeout == admin.request_timeout
    assert parsed_url.scheme == "https"
    assert parsed_url.netloc == "api.example.test"
    assert parsed_url.path == "/posts"
    assert parse_qs(parsed_url.query) == {
        "page": ["2"],
        "page_size": ["25"],
        "userId": ["7"],
    }


def test_project_pagination_forwards_page_and_page_size(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get(
        "/admin/tests/projectsmokepost/",
        {"p": "3", "per_page": "10"},
    )
    request.user = ProjectSmokeUser()
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeAPIResponse(
            [{"id": 301, "userId": 3, "title": "Page three row", "body": "page"}],
            total=42,
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, _fields = admin.get_api_data(request)
    rows = list(queryset)

    assert [row.id for row in rows] == [301]
    parsed_url = urlparse(calls[0][0])
    assert parse_qs(parsed_url.query) == {
        "page": ["3"],
        "page_size": ["10"],
    }


def test_project_filtering_forwards_filter_params_and_total(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get(
        "/admin/tests/projectsmokepost/",
        {"userId": "7", "title": "Filtered API row"},
    )
    request.user = ProjectSmokeUser()
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeAPIResponse(
            [
                {
                    "id": 701,
                    "userId": 7,
                    "title": "Filtered API row",
                    "body": "matched",
                }
            ],
            total=1,
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, fields = admin.get_api_data(request)
    rows = list(queryset)

    assert fields == ["userId", "title", "body"]
    assert len(rows) == 1
    assert rows[0].userId == 7
    assert rows[0].title == "Filtered API row"
    assert getattr(admin, "_api_filtered_total") == 1
    parsed_url = urlparse(calls[0][0])
    assert parse_qs(parsed_url.query) == {
        "page": ["1"],
        "page_size": ["25"],
        "userId": ["7"],
        "title": ["Filtered API row"],
    }


def test_project_default_list_display_keeps_id_link_and_api_fields(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get("/admin/tests/projectsmokepost/")
    request.user = ProjectSmokeUser()

    def fake_get(url, timeout):
        return FakeAPIResponse(
            [
                {"id": 101, "userId": 7, "title": "First API row", "body": "alpha"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    assert admin.get_list_display(request) == ["__str__", "userId", "title", "body"]
    assert admin.export_list == ["userId", "title", "body"]


def test_project_native_list_display_controls_api_columns(monkeypatch):
    admin = ProjectOrderedAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get("/admin/tests/projectsmokepost/")
    request.user = ProjectSmokeUser()

    def fake_get(url, timeout):
        return FakeAPIResponse(
            [
                {"id": 101, "userId": 7, "title": "First API row", "body": "alpha"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, fields = admin.get_api_data(request)
    rows = list(queryset)

    assert fields == ["id", "title", "userId"]
    assert admin.get_list_display(request) == ["id", "title", "userId"]
    assert admin.export_list == ["id", "title", "userId"]
    assert rows[0].body == "alpha"


def test_project_native_list_display_passes_admin_checks():
    admin = ProjectOrderedAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))

    errors = admin.check()

    assert "admin.E108" not in {error.id for error in errors}


def test_project_api_exclude_fields_hides_auto_columns(monkeypatch):
    admin = ProjectExcludeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    request = RequestFactory().get("/admin/tests/projectsmokepost/")
    request.user = ProjectSmokeUser()

    def fake_get(url, timeout):
        return FakeAPIResponse(
            [
                {"id": 101, "userId": 7, "title": "First API row", "body": "alpha"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    assert admin.get_list_display(request) == ["__str__", "userId", "title"]
    assert admin.export_list == ["userId", "title"]


def test_project_sorting_forwards_order_and_sorts_current_page(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    admin.api_list = ["userId", "title", "body"]
    request = RequestFactory().get(
        "/admin/tests/projectsmokepost/",
        {"o": "-2", "p": "1", "per_page": "25"},
    )
    request.user = ProjectSmokeUser()
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeAPIResponse(
            [
                {"id": 201, "userId": 1, "title": "Alpha", "body": "first"},
                {"id": 202, "userId": 2, "title": "Zebra", "body": "second"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, _fields = admin.get_api_data(request)
    rows = list(queryset)

    assert [row.title for row in rows] == ["Zebra", "Alpha"]
    parsed_url = urlparse(calls[0][0])
    assert parse_qs(parsed_url.query) == {
        "page": ["1"],
        "page_size": ["25"],
        "_sort": ["title"],
        "_order": ["desc"],
    }


def test_project_sorting_desc_first_api_field(monkeypatch):
    admin = ProjectSmokeAdmin(ProjectSmokePost, AdminSite(name="project-smoke"))
    admin.api_list = ["userId", "title", "body"]
    request = RequestFactory().get(
        "/admin/tests/projectsmokepost/",
        {"o": "-1", "p": "1", "per_page": "25"},
    )
    request.user = ProjectSmokeUser()
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return FakeAPIResponse(
            [
                {"id": 201, "userId": 1, "title": "Alpha", "body": "first"},
                {"id": 202, "userId": 2, "title": "Zebra", "body": "second"},
            ],
        )

    monkeypatch.setattr("django_api_factory.admin.requests.get", fake_get)

    queryset, _fields = admin.get_api_data(request)
    rows = list(queryset)

    assert [row.userId for row in rows] == [2, 1]
    parsed_url = urlparse(calls[0][0])
    assert parse_qs(parsed_url.query) == {
        "page": ["1"],
        "page_size": ["25"],
        "_sort": ["userId"],
        "_order": ["desc"],
    }
