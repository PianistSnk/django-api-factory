# Example 2: Local mock server (100k rows + 4 envelope shapes)

A more involved Django project that demonstrates:

- **The 100k-row performance case** — `BigPost` against the local
  mock server, with server-side pagination + cross-page filter.
- **All 4 industry-standard envelope shapes** — same dataset under
  `/posts-bare` (top-level list), `/posts-data` (`{"data": [...]}`),
  `/posts-items` (`{"items": [...]}`), `/posts-results`
  (`{"results": [...]}`). Proves `APIModel.parse_response` handles
  all 4 with zero per-admin boilerplate.

## What you'll see

- **`/admin/api/bigpost/`** — 100k posts, 200 per page → 500 pages.
  Try `?userId=1` (server-side filter), `?o=1` (sort by userId),
  `?q=qui+est+esse` (search).
- **`/admin/api/postbare/`** — 100 posts, top-level list.
- **`/admin/api/postdata/`** — 100 posts, `{"data": [...]}` envelope.
- **`/admin/api/postitems/`** — 100 posts, `{"items": [...]}` envelope.
- **`/admin/api/postresults/`** — 100 posts, `{"results": [...]}` envelope.

All 4 envelope admins render the **same 5 rows** (id 1-5) but from
different response shapes — the proof that `parse_response` works.

## Quick start

```bash
# 1. From the repo root, install the framework
cd ../..   # the django-api-factory repo root
pip install -e .

# 2. Install Django
pip install "django>=5.0,<6.0"

# 3. Start the local mock server (separate terminal)
python spikes/big-data-mock/server.py --port 8200 --rows 100000

# 4. Run this example
cd examples/local-mock
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/admin/` in your browser.

## What it demonstrates

- **Server-side pagination** — `BigPost` declares
  `expected_total = 100_000` and the framework's `get_api_data`
  asks the API for just the current page (e.g.
  `?_page=2&_limit=200`). 100k rows render at 47ms / 67KB instead
  of 44s / 40MB.
- **Cross-page filter** — the mock server honors `?userId=N&title=...
  &body=...&id=N` and returns the filtered slice with the right
  `X-Total-Count` header. The paginator then renders the right
  number of pages for the filtered set.
- **Envelope unwrap** — 4 admin pages, 4 different response
  shapes, **zero per-admin override**. Just point each `urls()` at
  a different mock path; `APIModel.parse_response` does the rest.
- **Filter distinct cap** — `filter_distinct_limit = 200` keeps
  the dropdown HTML at ~1MB (not 41MB), and the cap is configurable
  per admin.

## Files of interest

- `api/models.py` — 5 `APIModel` subclasses (`BigPost` + the 4
  envelope demos)
- `api/admin.py` — 5 `APIAdmin` registrations
- `../../spikes/big-data-mock/server.py` — the local mock server
  (3 lines to start: `python server.py --port 8200 --rows 100000`)

## See also

- `M2_T2.1_MVP_DONE.md` / `M2_T2.1_F1_DONE.md` — the server-side
  pagination work this example showcases.
- `M2_FILTER_DISTINCT_DONE.md` / `M2_FILTER_CAP_DONE.md` — the
  per-field distinct + cap patterns used by `BigPost`'s filter
  dropdowns.
- `d64bfeb` — the commit that added the 4 envelope demo endpoints
  to the mock server.
