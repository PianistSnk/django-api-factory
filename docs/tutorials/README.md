# Tutorials

Step-by-step guides for getting the most out of `django-api-factory`.

| # | Title | Time | Prerequisite |
|---|---|---|---|
| 1 | [Hello, APIModel](01-hello-apimodel.md) | 15 min | None |
| 2 | [Filter, search, sort](02-filter-search-sort.md) | 20 min | Tutorial 1 |
| 3 | [Cache, export, custom actions](03-cache-export-actions.md) | 25 min | Tutorial 2 |

**Total**: 60 minutes, from zero to a production-shaped admin tool.

## After the tutorials

- **Multiple examples**: see the `examples/` directory in the repo root
  for JSONPlaceholder, a local 100k-row mock server, a real wide API,
  and 4 response-envelope demos (`postbare` / `postdata` / `postitems`
  / `postresults`).
- **Architecture notes**: see `../reference/design-decisions.md`.
- **API reference**: see `README.md` § 7 for the `APIModel.parse_response`
  envelope hook, and `../reference/api-response-format.md` for response
  parsing behavior.
