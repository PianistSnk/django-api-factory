# Changelog

All notable changes to `django-api-factory` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-05

### Added
- `APIModel` abstract base + `APIAdmin` for mounting REST API data in Django admin.
- Server-side pagination, cross-page filtering, sorting, search, and export hooks.
- Optional ElementUI-style multi-select filters with native fallback.
- Django view-permission integration for API-backed admin pages.
- Two maintained examples under `examples/`: JSONPlaceholder and local mock.
- Documentation site, tutorials, and PyPI publish workflow.

### Fixed
- Built wheels include Django admin templates.
- The local mock server now lives inside `examples/local-mock/`.
- Generated caches, coverage output, local databases, and internal milestone notes
  are excluded from the release tree.
