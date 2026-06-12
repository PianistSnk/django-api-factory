# Tutorial 1: Hello, APIModel

> Time: 15 minutes
> Audience: Django developers who've never used `django-api-factory` before.
> Goal: Get a public REST API rendering inside Django admin — no frontend, no migrations, no DB writes.

---

## What you'll build

A Django admin page that lists the 100 posts from
[JSONPlaceholder](https://jsonplaceholder.typicode.com/posts), with
pagination, search, and a detail page. **~30 lines of Python total**.

![post admin changelist](https://placehold.co/600x300?text=Changelist+screenshot+here)

---

## 1. Set up a fresh Django project (3 min)

```bash
# Use any Python 3.9+; this tutorial was written against 3.11.
python -m venv .venv
source .venv/bin/activate
pip install "django>=5.0,<6.0" "django-api-factory"
```

> If you're on macOS and use `zsh`, the activation command is the same.

```bash
django-admin startproject myproject
cd myproject
python manage.py migrate              # admin needs auth tables
python manage.py createsuperuser     # pick any username/password
```

You should now have:

```
myproject/
├── manage.py
├── myproject/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
```

---

## 2. Add the app that will hold your models (1 min)

```bash
python manage.py startapp blog
```

Wire it up in `myproject/settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # ↑ the 6 default apps
    "django_api_factory",  # ← add this
    "blog",                # ← and this
]
```

---

## 3. Write the `APIModel` subclass (5 min)

Edit `blog/models.py`:

```python
from django_api_factory.models import APIModel


class Post(APIModel):
    """
    A Post sourced from JSONPlaceholder — a public fake REST API.

    The two abstract methods you MUST implement:
    - urls():  return the full URL to GET
    - cache(): return a Redis cache key, or None to disable caching
    """

    @classmethod
    def urls(cls, **kwargs) -> str:
        return "https://jsonplaceholder.typicode.com/posts"

    @classmethod
    def cache(cls, **kwargs):
        # Returning None disables caching for this model.
        return None

    class Meta(APIModel.Meta):
        verbose_name = "博客文章 (JSONPlaceholder)"
        verbose_name_plural = "博客文章 (JSONPlaceholder)"
```

> `APIModel` is `abstract = True` and `managed = False` — **no database
> table is created**. The data lives in someone else's API.

**Why two methods and not zero?**

- `urls()` declares "where to GET". Yours can accept `**kwargs`
  (the admin will pass `page=2` or `userId=1` for server-side filter
  later — see Tutorial 2).
- `cache()` declares a Redis key prefix. Return `None` to disable
  caching entirely — the default is **no Redis required**.

---

## 4. Register the admin (2 min)

Edit `blog/admin.py`:

```python
from django.contrib import admin
from django_api_factory.admin import APIAdmin

from .models import Post


@admin.register(Post)
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
```

> `APIAdmin` is a drop-in `ModelAdmin` subclass. Anything you can do
> with a normal Django admin, you can do here.

---

## 5. Run it (1 min)

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/blog/post/` in your browser, log in
with the superuser you created earlier. You should see:

- A paginated table with 20 posts per page
- The id, userId, and title columns
- The Django admin search bar (try searching "qui est esse")
- Click any post to see a detail page

**If you got here, congratulations** — you have a working CRUD-free
admin for an external API. The whole tutorial so far is 30 lines.

---

## 6. What just happened?

When the admin loads `/admin/blog/post/`:

1. `APIAdmin.get_api_data(request)` is called.
2. It calls `Post.urls()` to get `https://jsonplaceholder.typicode.com/posts`.
3. It does a `requests.get()` to that URL and gets 100 posts back as JSON.
4. `APIModel.parse_response` (default) sees a top-level list and accepts it.
5. The framework synthesizes fake model instances from each row.
6. Django admin's standard `ChangeList` paginates + renders the table.

**No SQL is ever run for Post.** The auth tables and the framework's
internal bookkeeping are the only database activity.

---

## What's next

- **Tutorial 2** adds server-side filter, search, and sort — turning
  the read-only changelist into something you can actually use for
  data ops.
- **Tutorial 3** adds Redis caching, a custom Excel export action,
  and a Modal-form action — the full "zero-friction internal tool"
  pattern.

---

## Troubleshooting

**`ImportError: No module named 'django_api_factory'`**

You forgot to add `"django_api_factory"` to `INSTALLED_APPS`. The
`APIModel` abstract base needs the AppConfig's `post_migrate` signal
to strip the auto-generated `add`/`change`/`delete` permissions.

**Admin shows 0 posts / "0 results"**

Open the browser's DevTools Network tab and visit
`https://jsonplaceholder.typicode.com/posts` directly. If it returns
a list of 100 dicts, the framework is misconfigured. If it returns
a wrapped envelope (e.g. `{"data": [...]}`), the default
`parse_response` will raise a `ValueError` with guidance — see
`README.md` § 7 for the 4 envelope shapes we support out of the box.

**`DisallowedHost` error**

Add `"127.0.0.1"` and `"localhost"` to `ALLOWED_HOSTS` in settings.py.
