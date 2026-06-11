# Changelog

All notable changes to `django-api-factory` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-dev0] - 2026-06-11

### Added
- Initial public release of `django-api-factory`
- 142 tests with 72.83% coverage (`--cov-fail-under=70` enforced in `pyproject.toml`)
- `APIAdmin` + `APIModel` for mounting any REST API as a Django admin model — no frontend, no database, no migrations
- 6 customization hooks: multi-value separator, audit log mixin, modal-form actions, pluggable cache backend, schema registry (thread-safe), changelist cache
- 4 working examples in `example/`: Post (jsonplaceholder 100 rows), BigPost (local mock 100k rows), CoinGecko (14k markets), User
- `spikes/big-data-mock/` — local 100k-row REST mock for performance testing
- `WALKTHROUGH.md` — 15-minute project tour for new contributors

### Fixed
- Cold-clone `pip install -e ".[dev]" && pytest` now passes 142/0 (was 9 fail with `ModuleNotFoundError: redis`); redis moved from `[cache]` extras to `[dev]`, and `tests/test_cache.py` gained a `pytest.importorskip("redis")` guard
- 6 pytest warnings cleaned: `TestModel` → `SchemaModel` (avoids pytest collection warning), `DistinctTestModel` collision resolved (line 765 renamed to `DistinctTestModelB`), `PagedPost` test fixture now has `Meta.ordering` (silences `UnorderedObjectListWarning`)
- Internal placeholder strings ("the team", "the original code/APIFactory", "the teaminternal project name") removed from `WALKTHROUGH.md` for the public release

### Notes
- This is a pre-release (`0.1.0-dev0`). PyPI publish is planned for the next sprint
  (see `M4` in the project roadmap). Until then, install via `pip install -e .`
  from a clone, or `pip install "git+https://github.com/PianistSnk/django-api-factory.git"`
