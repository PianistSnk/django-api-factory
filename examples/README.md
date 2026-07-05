# Examples

Two standalone Django projects, each demonstrating `django-api-factory`
against a different data source.

| Project | Data source | What it shows |
|---|---|---|
| [`jsonplaceholder/`](jsonplaceholder/) | [JSONPlaceholder](https://jsonplaceholder.typicode.com/) (public REST API) | The "hello world" — 100 posts + 10 users, ~40 lines of Python total. No auth, no rate limits, perfect for first contact. |
| [`local-mock/`](local-mock/) | Local `examples/local-mock/mock_server.py` (100k rows in-memory) | 100k-row performance case + all 4 industry-standard envelope shapes (bare list, `data`, `items`, `results`). Use this when the upstream API is paginated and large. |

## Quick start (any example)

```bash
# From the repo root:
pip install -e ".[dev]"
cd examples/<name>
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The `local-mock/` example also needs the mock server running in a
separate terminal (see its `README.md`).

## After the examples

- For the line-by-line tutorial, see `docs/tutorials/`.
- For design notes, see `docs/reference/design-decisions.md`.
- For response envelope behavior, see `docs/reference/api-response-format.md`.
