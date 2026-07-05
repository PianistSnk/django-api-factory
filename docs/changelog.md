# Changelog

All notable changes to `django-api-factory` will be documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-07-06

### Added
- Native Django `list_display` support for API response fields, so
  admins can control visible columns and order with the standard
  ModelAdmin API.
- `APIAdmin.api_exclude_fields` for auto-generated columns. The default
  excludes `id` because the row link already covers the detail target.

### Changed
- Moved API display-field control from `APIModel` to `APIAdmin`, matching
  Django admin's separation between data shape and presentation.
- Updated docs and examples to use `list_display = ["id", "userId", "title"]`.

### Removed
- Removed `APIModel.black_fields`; field hiding is now an admin-level concern.

### Fixed
- Sort mapping now follows native `list_display` order, including descending
  sort on the first API field.

## [0.1.0] - 2026-07-05

### Added
- **`APIModel.parse_response` hook** — 4 industry-standard
  envelope shapes (bare list, `{data: [...]}`, `{items: [...]}`,
  `{results: [...]}`) with override path for exotic formats.
- **4-envelope demo project** — `examples/local-mock/` has 4 admin
  pages pointing at 4 different response shapes, proving the
  default `parse_response` works with zero per-admin override.
- **Tutorials** — 3 step-by-step English tutorials under
  `docs/tutorials/` (60 minutes total, from zero to production-shaped).
- **Examples** — 2 standalone Django projects under `examples/`
  (jsonplaceholder + local-mock).
- **Auto-publish workflow** — `.github/workflows/publish.yml`
  builds + publishes to PyPI on tag push.
- **mkdocs documentation site** — this site, auto-deployed to
  GitHub Pages.
- **ElementUI-style admin filters** — optional multi-select filter
  UI with native fallback when SimpleUI is not installed.
- **Django permission integration** — API-backed admin pages expose
  view permissions through Django's permission system.

### Fixed
- `UnorderedObjectListWarning` from `Django Paginator` on every
  changelist render — silenced by `MyQuerySet.ordered = True`
  (the cache is ordered; the warning was a false positive).
- Cross-page sorting, filtering, and page-size handling for
  API-backed changelists.
- Package data configuration so Django admin templates are included
  in built wheels.

## Pre-release work - 2026-06-08

### Added
- Initial public release of `django-api-factory`.
- `APIModel` abstract base + `APIAdmin` class.
- `parse_response` — added post-initial-release.
- 4 envelope-shape demo endpoints in the local mock server.
- 218 tests / 84.86% coverage.
