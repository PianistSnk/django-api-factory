"""Admin registrations for the jsonplaceholder example.

The smallest possible config: each admin uses `get_list_display` to
build the column list dynamically from the API's actual response
fields. This avoids Django admin's strict "E108: field not on model"
check at startup — the API fields are not real Django model fields,
they're runtime data.

See Tutorial 1 (docs/tutorials/01-hello-apimodel.md) for the
line-by-line walkthrough, and the main `example/api/admin.py` for
the canonical version with cache + actions + filters wired up.
"""

from django.contrib import admin
from django.contrib.admin.utils import lookup_field

from django_api_factory.admin import APIAdmin
from django_api_factory.filter import APIFilter, APIMultiSelectFilter

from .models import Post, User


@admin.register(Post)
class PostAdmin(APIAdmin):
    """JSONPlaceholder Post admin — the tutorial 1 + 2 baseline."""
    list_display_links = ["__str__"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]

    def get_list_display(self, request):
        # API fields (id / userId / title / body) aren't Django model
        # fields, so we can't list them in `list_display` directly
        # without breaking Django's startup check. Build it dynamically
        # from the actual API response.
        if not self.api_list:
            self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        valid = ["__str__"]
        for f in self.api_list:
            try:
                lookup_field(f, self.model, self)
                valid.append(f)
            except Exception:
                pass
        return valid


@admin.register(User)
class UserAdmin(APIAdmin):
    """JSONPlaceholder User admin — 10 users, no pagination needed."""
    list_display_links = ["__str__"]
    list_per_page = 20
    search_fields = ["name", "username", "email"]
    list_filter = [
        ("name", APIMultiSelectFilter),
    ]

    def get_list_display(self, request):
        if not self.api_list:
            self.api_data, self.api_list = self.get_api_data(request)
        self.export_list = self.api_list
        valid = ["__str__"]
        for f in self.api_list:
            try:
                lookup_field(f, self.model, self)
                valid.append(f)
            except Exception:
                pass
        return valid
