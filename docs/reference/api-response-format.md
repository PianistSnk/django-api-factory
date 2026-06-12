# API response format

`django-api-factory` follows the [REST convention](https://jsonapi.org/format/)
used by [jsonplaceholder](https://jsonplaceholder.typicode.com/),
[GitHub](https://docs.github.com/en/rest),
[Stripe](https://stripe.com/docs/api), and
[Google Cloud](https://cloud.google.com/apis/design):
**list endpoints return a bare array**.

```http
GET /api/orders         → 200 [{...}, {...}, ...]   ← recommended (REST canonical)
GET /api/orders?page=2  → 200 [{...}, ...]          ← pagination via query params
```

For compatibility, `APIModel.parse_response` also handles 3 envelope
shapes that appear in real APIs (in priority order, first match wins):

| Response body                          | Source                                                |
| -------------------------------------- | ----------------------------------------------------- |
| `[{...}]`                              | REST canonical (jsonplaceholder / GitHub / Stripe)   |
| `{"data": [...]}`                      | Custom internal APIs / Laravel default                |
| `{"items": [...]}`                     | Older internal APIs                                   |
| `{"results": [...]}`                   | Django REST Framework `PageNumberPagination` default  |

## If your API uses something else

Override `parse_response` on your `APIModel` subclass:

```python
class LegacyOrder(APIModel):
    @classmethod
    def parse_response(cls, response_data):
        if isinstance(response_data, list):
            return response_data
        return response_data.get("payload", {}).get("rows", [])
```

The default raises `ValueError` with a clear message telling you how
to override — so a misconfigured envelope shows up immediately rather
than silently rendering an empty changelist.

## Why these 4 and not more

We deliberately do not invent a 5th canonical key (e.g. `payload`,
`rows`, `list`) — the four shapes above cover the formats used by
the major API ecosystems. If you control the API, **return a bare
array** and you won't need this hook at all.

## See also

- [Tutorial 1: Hello, APIModel](../tutorials/01-hello-apimodel.md) —
  the basic `urls()` / `cache()` interface.
- [Tutorial 2: Filter, search, sort](../tutorials/02-filter-search-sort.md) —
  how `urls(**kwargs)` forwarding works for cross-page filter.
- [Design decisions](design-decisions.md) — full rationale on
  "why Template Method instead of Strategy / Adapter for envelope
  unwrap".
