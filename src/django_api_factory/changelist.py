from django.contrib.admin.views.main import ChangeList


# GET params the APIAdmin consumes but the standard ChangeList would
# otherwise mistake for ORM lookups (and crash with FieldDoesNotExist →
# IncorrectLookupParameters → redirect to `?e=1`).
#
# IMPORTANT: this set must stay in sync with the `reserved` set used in
# `APIAdmin.get_api_data`'s in-memory filter loop, otherwise the same
# param would either crash ChangeList (lookup_param path) or silently
# zero out the result list (filter path). The admin.py `reserved` is
# hard-coded in that one spot; here we re-declare it for clarity.
APIADMIN_RESERVED_GET_PARAMS = frozenset({
    "per_page",  # per-page selector (?per_page=N overrides list_per_page)
})


class APIChangeList(ChangeList):
    """
    ChangeList for APIAdmin. Two fixes over the stock ChangeList:

    1. Strip reserved GET params (like `per_page`) from the filter
       lookup, so they don't get fed into `qs.filter(...)` as if they
       were model lookups (would crash with FieldDoesNotExist →
       IncorrectLookupParameters → redirect to `?e=1`).

    2. Force the per-page slicing path. Stock ChangeList's `get_results`
       short-circuits with `if (show_all and can_show_all) or not multi_page:
       result_list = self.queryset._clone()` — it skips `paginator.page(N)`
       when the dataset fits on one page. For our admin that means
       `?per_page=3` on UserAdmin (10 rows) is IGNORED: stock code
       sees `10 <= 50` and returns the full queryset. We override
       `get_results` to always go through `paginator.page(N)`, so the
       per-page slicing in `_APIPaginator.page` actually runs.
    """

    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params)
        for reserved in APIADMIN_RESERVED_GET_PARAMS:
            lookup_params.pop(reserved, None)
        return lookup_params

    def get_results(self, request):
        # Compute pagination (sets self.paginator, self.result_count, etc.)
        # by calling super, then forcibly route result_list through
        # paginator.page() so per-page slicing always applies.
        paginator = self.model_admin.get_paginator(
            request, self.queryset, self.list_per_page
        )
        # Mirror the relevant state that stock get_results would set
        # before doing the page() call. The stock get_results also does
        # this; we replicate so the rest of the admin can rely on it.
        self.paginator = paginator
        # Expose the EFFECTIVE per_page (after `?per_page=N` override) on
        # `cl` so the per-page selector template can mark the right
        # option as `selected`. Without this, the selector always shows
        # 10 selected because `cl.list_per_page` is the class attr.
        self.effective_per_page = paginator.per_page
        # Decide multi_page using the EFFECTIVE per_page (which may
        # have been overridden by `?per_page=N` in the admin's
        # get_paginator). We can't read paginator.per_page here because
        # get_paginator already applied the override; we DO have it
        # via the paginator instance.
        self.result_count = paginator.count
        can_show_all = self.result_count <= self.list_max_show_all
        # multi_page = total > per_page. Using paginator.per_page so the
        # `?per_page=N` override takes effect.
        multi_page = self.result_count > paginator.per_page
        # F1: clamp page_num to [1, num_pages] so paginator.page(N) and
        # the template's paginator.get_elided_page_range(N) both never
        # see an out-of-range page (which would raise EmptyPage → 500).
        # We silently clamp to the last page rather than Django stock's
        # `?e=1` redirect — friendlier when a user pastes a too-large
        # `?p=` from an old session, or when filter changes shrink the
        # page count.
        if paginator.num_pages > 0:
            self.page_num = min(max(1, self.page_num), paginator.num_pages)
        if self.show_all and can_show_all:
            result_list = self.queryset._clone()
        else:
            try:
                result_list = paginator.page(self.page_num).object_list
            except Exception:
                # Fall back to the full queryset rather than crash the
                # page on a bad page number.
                result_list = self.queryset._clone()
        self.result_list = result_list
        self.show_full_result_count = self.model_admin.show_full_result_count
        # `full_result_count` is the total count of all rows (across all
        # pages). For us it's `paginator.count` (which is `expected_total`
        # when declared, else the cache size). The "None total" we used
        # to write here rendered as the literal string "None" in the
        # "(None total)" suffix — fix that.
        self.full_result_count = self.result_count
        self.can_show_all = can_show_all
        self.multi_page = multi_page
        self.show_admin_actions = not self.show_full_result_count or bool(
            self.full_result_count
        )
