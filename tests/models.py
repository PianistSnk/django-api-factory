"""Empty models module — makes `tests/` a proper Django app.

Django's `create_permissions` (called from the `post_migrate` signal)
uses `app_config.get_models()` to find the models whose permissions
should be auto-generated. That method requires `app_config.models_module`
to point at a real Python module — without it, `get_models()` returns
an empty list, and `create_permissions` creates zero Permission rows
for the `tests` app (which is where our test-only concrete subclass
`_PermTestModel` lives).

This file exists solely to satisfy that requirement. It deliberately
contains no model definitions — defining models here would pollute
test isolation (each test file wants to define its own throwaway
test models).
"""
