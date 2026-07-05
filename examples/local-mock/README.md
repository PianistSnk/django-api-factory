# Example 2: Local mock server + real wide API

A more involved Django project that demonstrates:

- **The 100k-row performance case** — `BigPost` against the local
  mock server, with server-side pagination + cross-page filter.
- **A real small wide external API** — `DummyJSONUser` against
  `https://dummyjson.com/users?limit=1000`, with 45+ flattened fields.
- **Common envelope shapes** — same dataset under
  `/posts-bare` (top-level list), `/posts-data` (`{"data": [...]}`),
  `/posts-items` (`{"items": [...]}`), `/posts-results`
  (`{"results": [...]}`). Proves `APIModel.parse_response` handles
  common shapes with zero per-admin boilerplate.

## What you'll see

- **`/admin/api/bigpost/`** — 100k posts, 2000 per page → 50 pages.
  Try `?userId=1` (server-side filter), `?o=1` (sort by userId),
  `?q=qui+est+esse` (search).
- **`/admin/api/dummyjsonuser/`** — real DummyJSON users, fetched with
  `limit=1000` and flattened into 45+ fields from nested profile data.
- **`/admin/api/postbare/`** — 100k posts, top-level list.
- **`/admin/api/postdata/`** — 100k posts, `{"data": [...]}` envelope.
- **`/admin/api/postitems/`** — 100k posts, `{"items": [...]}` envelope.
- **`/admin/api/postresults/`** — 100k posts, `{"results": [...]}` envelope.

All 4 envelope admins render the same paginated dataset but from different
response shapes — the proof that `parse_response` works.

## Quick start

```bash
# 1. From the repo root, install the framework
cd ../..   # the django-api-factory repo root
pip install -e .

# 2. Install Django
pip install "django>=5.0,<6.0"

# 3. Start the local mock server for BigPost/envelope demos (separate terminal)
python examples/local-mock/mock_server.py --port 8200 --rows 100000

# 4. Run this example; the DummyJSON admin page also needs internet access
cd examples/local-mock
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/` in your browser.

## What it demonstrates

- **Server-side pagination** — `BigPost` asks the API for just the
  current page (e.g. `?_page=2&_limit=2000`) and reads the live total
  from the API's `X-Total-Count` header instead of hard-coding
  `expected_total`.
- **Cross-page filter** — the mock server honors `?userId=N&title=...
  &body=...&id=N` and returns the filtered slice with the right
  `X-Total-Count` header. The paginator then renders the right
  number of pages for the filtered set.
- **Real wide-schema compatibility** — DummyJSON returns nested user records;
  `DummyJSONUser` only declares `url`; `APIModel.parse_response` finds the
  `users` list and flattens nested address, bank, company, crypto, and profile
  metadata into admin columns without relying on a local mock API.
- **Envelope unwrap** — 4 admin pages, 4 different response
  shapes, **zero per-admin override**. Just point each `urls()` at
  a different mock path; `APIModel.parse_response` does the rest.
- **Default-all filters with exclusions** — `APIAdmin` auto-generates filters
  for every returned field, and `DummyJSONUserAdmin.list_filter_exclude`
  removes only noisy fields like image/password/long wallet values.

## Files of interest

- `api/models.py` — 6 `APIModel` subclasses (`BigPost`,
  `DummyJSONUser`, and the 4 envelope demos)
- `api/admin.py` — 6 `APIAdmin` registrations
- `mock_server.py` — the local mock server
  (start it from the repo root: `python examples/local-mock/mock_server.py --port 8200 --rows 100000`)

## See also

- `docs/tutorials/02-filter-search-sort.md` — filtering,
  searching, and sorting with `APIAdmin`.
- `docs/reference/api-response-format.md` — response envelope
  parsing behavior.
- `docs/reference/design-decisions.md` — pagination and
  schema design notes.
