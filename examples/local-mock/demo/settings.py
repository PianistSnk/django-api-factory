"""Django settings for the local-mock example.

Same minimal config as examples/jsonplaceholder, with one addition:
`ALLOWED_HOSTS` includes `127.0.0.1` so the local mock server
(also on 127.0.0.1) is reachable from the admin's `get_api_data`.

The mock server must be running separately:
    cd /path/to/django-api-factory
    python examples/local-mock/mock_server.py --port 8200 --rows 100000
"""

import os
from importlib.util import find_spec
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "local-mock-example-not-a-secret-key"

DEBUG = True
ALLOWED_HOSTS = ["*"]

OPTIONAL_ADMIN_THEME_APPS = []
if (
    os.environ.get("DJANGO_API_FACTORY_DEMO_SIMPLEUI") == "1"
    and find_spec("simpleui") is not None
):
    OPTIONAL_ADMIN_THEME_APPS.append("simpleui")

INSTALLED_APPS = OPTIONAL_ADMIN_THEME_APPS + [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_api_factory",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "demo.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "demo.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DJANGO_API_FACTORY_ELEMENTUI_FILTERS = (
    os.environ.get("DJANGO_API_FACTORY_ELEMENTUI_FILTERS", "0") == "1"
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
