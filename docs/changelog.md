# Changelog

All notable changes to `django-api-factory` will be documented in
this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **`APIModel.parse_response` hook** (T1.6b) — 4 industry-standard
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

### Fixed
- `UnorderedObjectListWarning` from `Django Paginator` on every
  changelist render — silenced by `MyQuerySet.ordered = True`
  (the cache is ordered; the warning was a false positive).

## [0.1.0-dev0] - 2026-06-08

### Added
- Initial public release of `django-api-factory`.
- `APIModel` abstract base + `APIAdmin` class.
- `parse_response` (T1.6b) — added post-initial-release.
- 4 envelope-shape demo endpoints in `spikes/big-data-mock/server.py`.
- 218 tests / 84.86% coverage.
