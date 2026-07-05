# Tutorial 2: Filter, search, sort

> Time: 20 minutes
> Prerequisite: completed [Tutorial 1](01-hello-apimodel.md).
> Goal: Turn the read-only changelist into a real data-ops tool with server-side filter, full-dataset search, and per-column sort.

---

## What you'll build

A Post admin where:

- The `userId` column has a filter dropdown showing all 10 userIds (not just the 20 on the current page)
- The title column has a search box
- Clicking a column header sorts the entire dataset
- `?userId=1` in the URL narrows to that user across all pages

![filter screenshot](https://placehold.co/600x300?text=Filter+UI+screenshot+here)

---

## 1. Add `list_filter` (5 min)

`list_filter` in Django admin takes either:

- A field name → builds a filter from that field's values
- A `(field_name, FilterClass)` tuple → uses a custom filter

`django-api-factory` ships `APIFilter` and `APIMultiSelectFilter`
in `django_api_factory.filter`. The first is a single-select dropdown,
the second is a multi-select checkbox list.

Edit `blog/admin.py`:

```python
from django.contrib import admin
from django_api_factory.admin import APIAdmin
from django_api_factory.filter import APIFilter, APIMultiSelectFilter

from .models import Post


@admin.register(Post)
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    list_filter = [
        ("userId", APIFilter),     # single-select dropdown: 1, 2, 3, ...
        ("body", APIMultiSelectFilter),  # multi-select checkbox list
    ]
```

> The filter dropdowns are populated from the **entire dataset**, not
> the current page. For 100 posts this is instant; for 100k see
> the local mock example for server-side pagination and large filter
> menus.

Reload `/admin/blog/post/` and you'll see a right-hand sidebar with
the userId and body filters. Clicking userId=1 filters to only user 1's
posts (10 of them).

---

## 2. Make `urls()` forward filter args (5 min)

Right now `Post.urls()` ignores any query params the admin passes
(filter selections, page number, sort key). For **cross-page** filter
to work, `urls()` must forward those params to the API.

Edit `blog/models.py`:

```python
from urllib.parse import quote

class Post(APIModel):
    @classmethod
    def urls(cls, page=1, page_size=50, **kwargs) -> str:
        # Build the base pagination query
        qs_parts = [f"_page={page}", f"_limit={page_size}"]
        # Forward any extra kwargs (filter values, sort, etc.) as query
        # params. The API applies them server-side before paginating.
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        return "https://jsonplaceholder.typicode.com/posts?" + "&".join(qs_parts)

    @classmethod
    def cache(cls, **kwargs):
        return None
```

JSONPlaceholder accepts `?userId=1` and returns only that user's
posts. Try the URL in your browser:

```
https://jsonplaceholder.typicode.com/posts?userId=1
```

→ 10 posts, all from user 1.

Now the admin's filter sidebar will narrow the dataset **across all
pages** instead of doing client-side filtering on the current page.

---

## 3. Add search (2 min)

Django admin has a built-in search bar that searches across multiple
fields. `search_fields` works the same as for a normal ModelAdmin.

```python
@admin.register(Post)
class PostAdmin(APIAdmin):
    list_display = ["id", "userId", "title"]
    list_per_page = 20
    search_fields = ["title", "body"]   # ← add this
    list_filter = [
        ("userId", APIFilter),
        ("body", APIMultiSelectFilter),
    ]
```

Try searching "qui est esse" in the search bar. By default the search
is **server-side**: the framework passes `?q=qui+est+esse` to your
`urls()` (you don't need to do anything; the API applies it). For
APIs that don't support `?q=`, the framework falls back to
client-side filtering on the current page.

---

## 4. Per-column sort (5 min)

Clicking a column header in Django admin emits a URL like `?o=2`
(the `2` is the 0-based index into `list_display`). The framework
translates that to the API's `?_sort=<field>&_order=asc` (or `desc`)
and forwards it through `urls(**kwargs)`.

For the framework to know which column maps to which field, the
API's JSON must include the field name verbatim. JSONPlaceholder does
this already (`"userId": 1, "id": 1, "title": "...", "body": "..."`),
so sort works automatically.

> **Gotcha**: `?o=N` is 0-based and points at `list_display`. With
> `list_display = ["id", "userId", "title"]`, `?o=1` sorts by
> `userId` and `?o=2` sorts by `title`.

Try clicking the "userId" column header — the URL becomes `?o=1` and
the framework asks the API for `?_sort=userId&_order=asc`.
Click again to toggle desc.

---

## 5. Verify end-to-end (2 min)

In your browser, hit these URLs and verify the result:

| URL | Expected |
|---|---|
| `/admin/blog/post/` | 100 posts, 5 pages of 20 |
| `/admin/blog/post/?userId=1` | 10 posts, 1 page (all from user 1) |
| `/admin/blog/post/?o=1` | sorted by userId ascending |
| `/admin/blog/post/?o=-1` | sorted by userId descending |
| `/admin/blog/post/?q=qui+est+esse` | 1 post, id=12 |

---

## What's next

- **Tutorial 3** adds Redis caching (so the second click is
  instant), a custom Excel export action, and a Modal-form action.
- For 100k+ datasets, see `../examples/local-mock/README.md` for
  server-side pagination, cross-page filtering, and large filter menus.
