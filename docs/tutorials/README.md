# Tutorials

Step-by-step guides for getting the most out of `django-api-factory`.

| # | Title | Time | Prerequisite |
|---|---|---|---|
| 1 | [Hello, APIModel](01-hello-apimodel.md) | 15 min | None |
| 2 | [Filter, search, sort](02-filter-search-sort.md) | 20 min | Tutorial 1 |
| 3 | [Cache, export, custom actions](03-cache-export-actions.md) | 25 min | Tutorial 2 |

**Total**: 60 minutes, from zero to a production-shaped admin tool.

## After the tutorials

- **Multiple examples**: see the `example/` directory in the repo root
  — it has 4 admin registrations covering JSONPlaceholder (public
  mock API), the local 100k-row mock server (`spikes/big-data-mock/`),
  and 4 envelope-shape demos (`postbare` / `postdata` / `postitems` /
  `postresults`).
- **Architecture deep-dive**: see `WALKTHROUGH.md` (中文讲解) or
  `docs/` (English, future work).
- **API reference**: see `README.md` § 7 for the `APIModel.parse_response`
  envelope hook, and `M1_*_DONE.md` for design decisions.
