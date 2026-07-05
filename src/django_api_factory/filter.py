from urllib.parse import urlsplit, urlunsplit

from django.contrib.admin import AllValuesFieldListFilter
from django.contrib.admin.views.main import PAGE_VAR
from django.http import QueryDict


class APIFilterChoice:
    """Value wrapper compatible with Django filters and SimpleUI options.

    Django's `AllValuesFieldListFilter` expects `lookup_choices` items to be
    raw values and calls `str(value)` when building links. SimpleUI's
    `search_form.html` expects each item to behave like `(value, label)` and
    reads `option.0` / `option.1`. This wrapper supports both contracts without
    storing tuple reprs in filter URLs.
    """

    __slots__ = ("label", "value")

    def __init__(self, value, label=None):
        self.value = value
        self.label = value if label is None else label

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return repr(self.value)

    def __getitem__(self, index):
        if index in (0, "0"):
            return self.value
        if index in (1, "1"):
            return self.label
        raise IndexError(index)

    def __iter__(self):
        yield self.value
        yield self.label

    def __len__(self):
        return 2

    def __eq__(self, other):
        if isinstance(other, APIFilterChoice):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)

    def __lt__(self, other):
        if isinstance(other, APIFilterChoice):
            other = other.value
        return self.value < other


class APIFilter(AllValuesFieldListFilter):
    template = "admin/django_api_factory/filter.html"

    is_multi = False

    def __init__(self, field, request, params, model, model_admin, field_path):
        original_params = params.copy()
        try:
            super().__init__(field, request, params, model, model_admin, field_path)
        except Exception:
            self.field = field
            self.field_path = field_path
            self.model_admin = model_admin
            self.model = model
            self.request = request
            self.params = params
            self.title = field.verbose_name
            self.empty_value_display = model_admin.get_empty_value_display()
        self.lookup_kwarg = field_path
        self.lookup_kwarg_isnull = "%s__isnull" % field_path
        self.lookup_val = self._first_lookup_value(
            original_params.get(self.lookup_kwarg)
        )
        self.lookup_val_isnull = self._first_lookup_value(
            original_params.get(self.lookup_kwarg_isnull)
        )
        if not hasattr(self, "empty_value_display") or self.empty_value_display is None:
            self.empty_value_display = model_admin.get_empty_value_display()
        # Filter choices: prefer the admin's get_filter_choices() (Jun
        # 2026 cross-page distinct) which can return the FULL enum
        # across the entire dataset, not just the current page's
        # values. Fall back to the current page's values if the admin
        # doesn't override (or the call fails).
        values, total_count = self._collect_choices(field, model_admin, request)
        self.raw_lookup_choices = values
        self.lookup_choices = self._wrap_lookup_choices(values)
        # Stash the TRUE total count on the spec so the template can
        # render "(X of Y)" when the choices are truncated. Legacy
        # callers (no get_filter_choices hook) get total = len(values).
        self._total_count = total_count
        # Same value under a name the template can access (Django
        # blocks attributes starting with `_`). The spec's JS reads
        # this via `data-total` on the <ul>.
        self.total_count = total_count
        # Override the title to include the TRUE total count only when the
        # filter is idle. Once values are selected, the trigger shows those
        # values as ElementUI-style tags, so the count badge becomes noise.
        base_title = field.verbose_name
        if self.lookup_val:
            self.title = base_title
        elif total_count > 0:
            self.title = f"{base_title} ({total_count})"
        # else: keep the default (no count)

    def _collect_choices(self, field, model_admin, request):
        """Build the distinct-values list for this filter.

        Older implementations read from `model_admin.json_to_filter`
        (the current API page), which limited the dropdown to that
        page's values. `model_admin.get_filter_choices(field.name,
        request)` lets subclasses fetch the full enum (e.g. via a
        `/distinct` endpoint) so the dropdown shows ALL distinct values
        across the whole dataset. We fall back to the per-page scan if
        the hook isn't present or raises.

        Returns (values_list, total_count) where total_count is the
        TRUE distinct count for the idle trigger badge. If the hook
        doesn't return a total, we use
        len(values) (no truncation info)."""
        get_choices = getattr(model_admin, "get_filter_choices", None)
        if callable(get_choices):
            try:
                result = get_choices(field.name, request)
                if isinstance(result, dict):
                    # New shape: {"values": [...], "count": N, "truncated": bool}
                    values = result.get("values") or []
                    total = result.get("count", len(values))
                elif result:
                    # Old shape: list of values (no truncation info)
                    values = result
                    total = len(values)
                else:
                    values = []
                    total = 0
                if values:
                    return self._dedup_and_normalize(field, values), total
            except Exception:
                pass  # fall through to legacy path
        # Legacy fallback: distinct values from the current API page.
        source = (getattr(model_admin, "json_to_filter", None) or [])
        values = self._dedup_and_normalize(
            field,
            (obj.get(field.name) for obj in source),
        )
        return values, len(values)

    def _dedup_and_normalize(self, field, values):
        # Use a set for O(1) membership checks instead of `value not
        # in out` against a list (which is O(n) and makes the whole
        # dedup O(n²) — 10k unique values = 100M comparisons, 5-10s
        # in pure Python). Values containing the configured multi-value
        # separator are canonicalized so different orders collapse.
        seen = set()
        out = []
        for value in values:
            if isinstance(value, str) and "\u3001" in value:
                value = "\u3001".join(sorted(value.split("\u3001")))
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    def _wrap_lookup_choices(self, values):
        return [
            value if value is None else APIFilterChoice(value)
            for value in values
        ]

    def _first_lookup_value(self, value):
        if isinstance(value, (list, tuple)):
            return value[0] if value else None
        return value

    def choices(self, changelist):
        for choice in super().choices(changelist):
            query_string = choice.get("query_string")
            if query_string:
                choice = choice.copy()
                choice["query_string"] = self._drop_page_param(query_string)
            yield choice

    def _drop_page_param(self, query_string):
        """Filter changes must start from page 1.

        Django's stock filter links keep the current `?p=N`. With
        server-side pagination, applying a filter while on page 20 asks
        the API for the filtered dataset's page 20, which is often empty.
        """
        parts = urlsplit(query_string)
        query = QueryDict(parts.query, mutable=True)
        query.pop(PAGE_VAR, None)
        encoded_query = query.urlencode()
        if not encoded_query and not parts.path:
            return "?"
        return urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            encoded_query,
            parts.fragment,
        ))


class APIMultiSelectFilter(APIFilter):
    """Multi-select variant of APIFilter. Renders checkboxes plus an
    "Apply" / "Clear" pair (modeled after simpleui's filter bar — pick
    many, commit in one click). URL format: ``?field=v1,v2,v3`` (a
    comma-separated list), which the in-memory filter in
    ``APIAdmin.get_api_data`` already handles as OR semantics via
    ``search_pars[field_name].split(',')`` — so no queryset plumbing
    is needed on this side.
    """
    is_multi = True
    trigger_tag_limit = 2

    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        self.selected_values = self._selected_values()
        self.selected_preview_values = self.selected_values[:self.trigger_tag_limit]
        self.selected_overflow_count = max(
            0,
            len(self.selected_values) - len(self.selected_preview_values),
        )

    def choices(self, changelist):
        selected_values = set(self.selected_values)
        for index, choice in enumerate(super().choices(changelist)):
            # Multi-select uses the explicit "Clear" action instead of an
            # "All" row. Keeping the "All" row as a checkbox would submit
            # `?field=All`, which is never a real data value.
            if index == 0:
                continue
            choice = choice.copy()
            value = self._choice_value(choice)
            choice["value"] = value
            choice["selected"] = value in selected_values
            yield choice

    def _choice_value(self, choice):
        query_string = choice.get("query_string") or ""
        parts = urlsplit(query_string)
        query = QueryDict(parts.query)
        value = query.get(self.lookup_kwarg)
        if value is None:
            value = choice.get("display", "")
        return str(value)

    def _selected_values(self):
        return [
            value
            for value in str(self.lookup_val or "").split(",")
            if value
        ]
