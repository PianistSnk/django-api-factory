"""
Django settings for the django-api-factory example project.

This example uses JSONPlaceholder (https://jsonplaceholder.typicode.com/) as
a stand-in for a real internal API. No auth, no rate limits, perfect for demo.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-change-me-in-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    # "simpleui",  # T1.2f: removed to verify core runs without simpleui
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "django_api_factory",  # core package (editable install)
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

ROOT_URLCONF = "example.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        # NOTE: Django 4.x auto-wraps the loaders list in
        # `cached.Loader` whenever `loaders` is unset — and
        # `cached.Loader` keys by `(template_name, skip)`, NOT by
        # file mtime, so template edits during a dev-server
        # session (--noreload) are silently ignored. Pin the
        # non-cached loaders here so saves take effect on the
        # next request. (Django's DEBUG flag no longer controls
        # this in 4.x.)
        "OPTIONS": {
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "example.wsgi.application"

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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Optional Redis settings — django-api-factory will fall back to no-cache if missing.
# REDIS_HOST = "127.0.0.1"
# REDIS_PORT = 6379
# REDIS_DB = 0
# REDIS_PWD = None
# REDIS_HOST = "127.0.0.1"  # T1.2f: commented out to verify NullCacheBackend fallback
# REDIS_PORT = 6379
# REDIS_DB = 0
REDIS_HOST = "127.0.0.1"   # T1.5e: re-enabled so detail-view cache actually stores
REDIS_PORT = 6379
REDIS_DB = 0
