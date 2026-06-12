# Design decisions

The major design choices in `django-api-factory`, with the rationale
and the alternatives that were considered.

## 1. Why a Template Method for envelope unwrap, not a Strategy / Adapter

The default `APIModel.parse_response` handles 4 industry-standard
response shapes. The user can override it for anything else.

Alternatives considered:

- **Strategy** (`response_list_key = "data"`): saves 1 line per admin,
  but adds a class attribute that's only useful for the 1% of APIs
  that wrap their list. For 5+ data sources, this is more typing
  than a 3-line `parse_response` override.
- **Adapter** (separate `ResponseAdapter` class): overkill for the
  common case. Users who need it can write a 3-line `parse_response`
  that delegates to their own adapter class — the framework doesn't
  need to ship the abstraction.
- **REST-only** (only support bare list): the strictest, but real
  APIs (DRF default = `{"results": [...]}`, Laravel = `{"data": [...]}`)
  would force users to wrap the framework. We prefer the framework
  to wrap the API.

We deliberately do not invent a 5th canonical key (`payload`,
`rows`, `list`) — the four we support cover the formats used by
jsonplaceholder, GitHub, Stripe, Google Cloud, and the DRF ecosystem.

See `M1_T1.6b_DONE.md` for the full decision log.

## 2. Why `managed = False` + `abstract = True` on `APIModel`

`APIModel` is `abstract = True` (no database table for the base
class) and `managed = False` (no migrations for subclasses). The
data lives in someone else's API — there is nothing to migrate to.

Alternative considered: `class Post(models.Model)` with a custom
manager that intercepts queries. Rejected because Django admin
introspects the model for `list_display`, `list_filter`, etc. —
faking it requires monkey-patching the model class at startup,
which is what `SchemaRegistry` does (see § 3). Having the data
model be an `APIModel` makes the contract explicit at type-check
time and in Django's admin autodiscover.

## 3. Why a `SchemaRegistry` instead of declaring fields on the model

`APIAdmin.get_list_display(request)` builds the column list at
request time from the API's actual response fields. The fields
get registered on the model class via `SchemaRegistry` so Django
admin's introspecting code (`lookup_field`, `list_filter` choices)
can find them.

Alternative considered: requiring users to declare each field as
a `models.CharField()` / `models.IntegerField()` on the APIModel
subclass. Rejected because:
- It's ceremony for what's really a runtime data shape
- It duplicates the API schema in two places (Python class + API)
- It would force users to redeclare the field type for every API
  they add (5+ data sources = 50+ field declarations)

The trade-off: field access (`obj.some_field`) only works after
the first request, since the schema isn't known until the API
responds. We accept this because the admin is a UI layer — it's
always hit after the first request anyway.

## 4. Why server-side pagination is mandatory for 100k+ datasets

`expected_total = N` is **required** when your API supports
`?page=N&page_size=M`. Without it, the paginator can't render the
right number of page links, and `?p=越界` raises 500.

The performance numbers (from the M2 spike):

| Dataset size | Without server-side pagination | With server-side pagination |
|---|---|---|
| 1k rows      | 60-80ms / 50KB                  | 60-80ms / 50KB               |
| 10k rows     | 1s / 5MB                        | 1s / 67KB                    |
| 100k rows    | 44s / 40MB (unusable)           | 47ms / 67KB                  |
| 1M rows      | crashes / OOM                   | 1s / 67KB                    |

Server-side pagination is **not** a nice-to-have for 10k+ rows.
See `M2_T2.1_MVP_DONE.md` and `M2_T2.1_F1_DONE.md`.

## 5. Why caching is opt-in, not auto-detected

`cache_backend_class` defaults to `NullCacheBackend` (no-op). To
use Redis, you must set it explicitly.

Alternatives considered:
- **Auto-detect from `settings.REDIS_HOST`**: rejected because it
  adds coupling between the framework and your project layout. If
  you have Redis configured for Celery, the framework shouldn't
  silently start caching your admin data.
- **Auto-detect from installed packages** (`pip install redis`):
  rejected for the same reason — installing redis for some other
  reason shouldn't enable admin caching.
- **Required `cache()` implementation**: rejected because 90% of
  users don't need caching, and forcing them to write `def cache(...): return None` is busywork.

The opt-in is intentional. See `M1_T1.2_DONE.md` for the
rationale.

## 6. Why `MyQuerySet.ordered = True` (silence UnorderedObjectListWarning)

Django's `Paginator` raises `UnorderedObjectListWarning` when the
object_list's `.ordered` is False. For our in-memory `MyQuerySet`,
the cache IS ordered (id-asc by default for server-side pagination;
user-driven `?o=` for client-side), but the default `ordered` is
inherited as False.

We force `ordered = True` as a class attribute. The paginator
warning was a **false positive** in our case, and it was making
real warnings in the log harder to spot.

If you build a custom APIModel subclass where the cache is
genuinely unordered (e.g. you're proxying a `set()` or something
truly unordered), override the cache before the paginator sees it,
or set `ordered = False` explicitly on your subclass.

## See also

- [API response format](api-response-format.md) — the envelope
  unwrap rationale in more detail.
- `M1_*_DONE.md` and `M2_*_DONE.md` in the repo root for
  milestone-level decision logs.
