# Example 1: JSONPlaceholder (public REST API)

A minimal Django project that mounts the public
[JSONPlaceholder](https://jsonplaceholder.typicode.com/) API as a
Django admin — no frontend, no DB, no auth tokens.

This is the **"hello world"** example. Two admin pages, ~40 lines of
Python total, runs in under 30 seconds from clone.

## What you'll see

- **`/admin/blog/post/`** — 100 posts from JSONPlaceholder, with
  pagination, search, filter by userId, and per-column sort.
- **`/admin/blog/user/`** — 10 users, paginated, with a multi-select
  name filter.

## Quick start

```bash
# 1. From the repo root, install the framework
cd ../..   # the django-api-factory repo root
pip install -e .

# 2. Install Django (not a runtime dep of django-api-factory)
pip install "django>=5.0,<6.0"

# 3. Run this example
cd examples/jsonplaceholder
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/blog/post/` in your browser.

## What it demonstrates

- **The smallest possible `APIModel` subclass** — 5 lines each.
- **Cross-page filter** — `?userId=1` returns only user 1's posts
  (the API applies it server-side; see Tutorial 2 for how
  `urls(**kwargs)` forwards the param).
- **Server-side sort** — clicking the `userId` column header emits
  `?o=1`; the framework translates that to `?_sort=userId&_order=asc`
  and JSONPlaceholder honors it.
- **Search** — the framework's default `?q=...` is forwarded to the
  API too.

## Files of interest

- `blog/models.py` — the two `APIModel` subclasses (Post, User)
- `blog/admin.py` — the two `APIAdmin` registrations
- `demo/settings.py` — minimal Django config

## Next step

For a more involved example with **100k rows**, server-side
pagination, multiple envelope shapes, and the full M2
performance/perf work, see
[`../local-mock/`](../local-mock/).
