"""End-to-end smoke test: load the example app, hit admin, see live API data.

Run directly with: python tests/test_e2e.py
"""
import os
import sys

# Add the example project to path so we can import its settings
EXAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "example")
sys.path.insert(0, EXAMPLE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")

import django
django.setup()

from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import Client


def main():
    # Run migrations to set up the auth tables
    call_command("migrate", verbosity=0, interactive=False)

    User.objects.update_or_create(
        username="e2e_admin",
        defaults={"is_staff": True, "is_superuser": True, "email": "a@a.com"},
    )
    u = User.objects.get(username="e2e_admin")
    u.set_password("pw")
    u.save()

    c = Client()
    assert c.login(username="e2e_admin", password="pw"), "login failed"

    print("→ GET /admin/api/post/")
    resp = c.get("/admin/api/post/")
    print(f"  status: {resp.status_code}, body size: {len(resp.content)} bytes")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8", errors="replace")
    assert "sunt aut facere" in body or "userId" in body, "Post API data missing"

    print("→ GET /admin/api/user/")
    resp = c.get("/admin/api/user/")
    print(f"  status: {resp.status_code}, body size: {len(resp.content)} bytes")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8", errors="replace")
    # JSONPlaceholder users have emails like Sincere@april.biz
    assert "Sincere" in body or "@" in body, "User API data missing"

    print("\nE2E OK ✓ — both Post and User admin changelists render live API data")


if __name__ == "__main__":
    main()
