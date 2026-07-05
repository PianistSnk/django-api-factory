"""Admin registrations for the jsonplaceholder example."""

from django.contrib import admin

from django_api_factory.admin import APIAdmin
from django_api_factory.filter import APIFilter, APIMultiSelectFilter

from .models import Post, User


@admin.register(Post)
class PostAdmin(APIAdmin):
    """JSONPlaceholder Post admin — the tutorial 1 + 2 baseline."""
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]


@admin.register(User)
class UserAdmin(APIAdmin):
    """JSONPlaceholder User admin — 10 users, no pagination needed."""
    list_display = ["id", "name", "username", "email", "phone", "website"]
    list_per_page = 20
    search_fields = ["name", "username", "email"]
    list_filter = [
        ("name", APIMultiSelectFilter),
    ]
