# django-api-factory

**Display any REST API as a Django admin model — no frontend, no migrations, just `urls()` and `cache()`.**

Three years of production-tested code distilled into a 200-line package.

## Why

Django admin is the fastest CRUD UI in existence. Why build a separate
frontend for data that lives in someone else's API?
`django-api-factory` lets you mount any REST endpoint as a Django admin
changelist — search, filter, sort, export, all for free.

## 30-second example

```python
# models.py
from django_api_factory.models import APIModel

class Post(APIModel):
    def urls(self, **kwargs):
        return "https://jsonplaceholder.typicode.com/posts"

    def cache(self, **kwargs):
        return None  # disable Redis

# admin.py
from django_api_factory.admin import APIAdmin

@admin.register(Post)
class PostAdmin(APIAdmin):
    pass
```

Run `python manage.py runserver`, log in, visit `/admin/api/post/`,
see your API data.

## Install

```bash
pip install django-api-factory
```

## Tutorials

Start with the [Hello, APIModel tutorial](tutorials/01-hello-apimodel.md)
(15 minutes) for a hands-on walkthrough, then move to
[Filter, search, sort](tutorials/02-filter-search-sort.md) and
[Cache, export, custom actions](tutorials/03-cache-export-actions.md)
for the full production-shaped pattern.

## Examples

Two standalone projects live in the `examples/` directory:

- [`examples/jsonplaceholder/`](examples/jsonplaceholder/README.md) —
  public REST API, ~40 lines of Python total. The "hello world".
- [`examples/local-mock/`](examples/local-mock/README.md) —
  100k-row performance case + all 4 industry-standard envelope
  shapes. Needs the local mock server running.

## Project status

- [x] **v0.1.0-dev0** — M0: shallow clone, works for read-only public APIs
- [x] **M1** — refactor + concurrency fixes + cache/audit hooks
- [x] **M2** — server-side pagination, cross-page filter, cross-page sort
- [x] **M3** — README, tutorials, examples
- [x] **M4** — CI, coverage, mkdocs docs site, auto-publish workflow
- [ ] M5: PyPI v0.1.0 release (gated on user signal)

See the [design decisions](reference/design-decisions.md) for the
full rationale on each major choice.

## License

MIT — see [License](license.md).
