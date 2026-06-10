"""M2 大数据集 spike — Mock REST server.

Mimics JSONPlaceholder shape (id / userId / title / body) so the same
APIAdmin code path works. Supports `?_page=N&_limit=M` pagination.

Usage:
    python spikes/big-data-mock/server.py --port 8200 --rows 100000
    curl 'http://127.0.0.1:8200/posts?_page=1&_limit=10'
"""

import argparse
import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fixed seed → identical data across runs (good for benchmarking)
random.seed(42)

# Pre-built dataset — built once at startup, served from memory.
# Tweak ROWS via --rows (1w / 10w / 100w). User count scales with row count.
DATA = {"posts": []}

TITLE_TEMPLATES = [
    "sunt aut facere repellat provident",
    "qui est esse",
    "ea molestias quasi exercitationem repellat qui ipsa sit aut",
    "eum et est occaecati",
    "nesciunt quas odio",
    "dolorem eum magni eos aperiam quia",
    "magnam facilis autem",
    "dolorem dolore est ipsam",
    "nesciunt iure omnis quia",
    "optio molestias id quia eum",
    # Jun 2026 expansion: 10 -> 30 templates. With 10 templates and
    # 100k rows, each template repeats 10_000 times. After sort-by-title
    # with per_page=10000, the user only saw ONE template's worth of
    # rows (visually looked like sort "didn't work" — every row had the
    # same title prefix). 30 templates -> ~3_333 each in 100k, so
    # per_page=10000 shows ~3 distinct template groups.
    "adipisci velit sed magnam",
    "alias voluptas aliquam doloribus",
    "asperiores ea ipsam voluptatem",
    "blanditiis consectetur expedita",
    "commodi consequuntur deleniti",
    "consequatur cupiditate deserunt",
    "cupiditate debitis deleniti",
    "deserunt distinctio dolorem",
    "distinctio doloribus ducimus",
    "eaque eius eligendi enim",
    "enim error esse expedita",
    "expedita explicabo fugiat",
    "fugiat harum hic illo",
    "illum impedit incidunt ipsam",
    "laboriosam libero maiores",
    "maiores modi molestiae mollitia",
    "necessitatibus nemo nihil nisi",
    "obcaecati odio officia optio",
    "pariatur perferendis perspiciatis",
    "placeat porro possimus praesentium",
]

BODY_TEMPLATES = [
    "quia et suscipit suscipit recusandae consequuntur expedita et cum reprehenderit molestiae",
    "est rerum tempore vitae sequi sint nihil reprehenderit dolor quia",
    "et iusto sed quo iure voluptatem occaecati omnis eligendi aut ad voluptatem doloribus",
    "sint et ea voluptas illo aperiam quaerat fuga voluptas reprehenderit amet",
    "in voluptate sit ea ut autem non aut corporis",
    "qui ratione porro omnis quia minus",
    "consectetur adipisci amet sit fugit sunt voluptatem",
    "voluptatem repellat sit provident aperiam voluptatem",
    "rerum voluptatem consequatur ut facere",
    "architecto et voluptas sint sit amet nemo aut consequuntur",
    # Jun 2026 expansion: 10 -> 30 (see TITLE_TEMPLATES comment)
    "blanditiis deserunt dolore doloremque doloribus ea eaque eius eligendi",
    "enim error esse est et eum expedita explicabo facilis",
    "fugiat harum hic id illo impedit in incidunt ipsa iste",
    "itaque iure iusto labore laboriosam libero magnam magni maiores",
    "maxime minima modi molestiae mollitia nam necessitatibus nemo nihil",
    "nisi nobis nostrum nulla obcaecati odio officia omnis optio",
    "pariatur perferendis perspiciatis placeat porro possimus praesentium quam",
    "quasi qui quia quisquam quo ratione recusandae reiciendis rem",
    "repellendus reprehenderit rerum saepe sapiente sed sequi similique",
    "sint sit sunt tempora tenetur totam ullam unde ut vel",
]


def build_dataset(n_posts: int) -> list:
    """Generate n_posts fake posts in JSONPlaceholder shape."""
    n_users = max(10, n_posts // 10)  # 1 user per 10 posts, min 10 users
    posts = []
    for i in range(1, n_posts + 1):
        user_id = ((i - 1) % n_users) + 1
        title = TITLE_TEMPLATES[i % len(TITLE_TEMPLATES)] + f" #{i}"
        body = BODY_TEMPLATES[i % len(BODY_TEMPLATES)] + f" (post {i})"
        posts.append({
            "id": i,
            "userId": user_id,
            "title": title,
            "body": body,
        })
    return posts


class MockHandler(BaseHTTPRequestHandler):
    """GET /posts?_page=N&_limit=M → JSON list of posts."""

    def log_message(self, fmt, *args):
        # Spike-mode: log every GET with response size + handler time
        import time
        if not hasattr(self, "_t0"):
            self._t0 = time.perf_counter()
        dt_ms = (time.perf_counter() - self._t0) * 1000
        sys.stderr.write(f"[mock] {self.command} {self.path} ({dt_ms:.1f}ms)\n")
        sys.stderr.flush()

    def do_GET(self):
        # /distinct?field=X[&limit=N&offset=M] (Jun 2026 filter-distinct,
        # capped). Returns distinct values for a field across the entire
        # dataset, optionally paginated. Without this, ?userId= dropdown
        # on 100k rows / 200 per page only shows 200 userIds, not the
        # real 10_000. With limit=N, the response stays small (N values)
        # so the admin HTML doesn't explode to 41MB.
        if self.path.startswith("/distinct"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            field = (qs.get("field") or [None])[0]
            if not field:
                self.send_error(400, "Missing ?field=<name>")
                return
            limit = int((qs.get("limit") or [None])[0] or 0)
            offset = int((qs.get("offset") or [None])[0] or 0)
            # Server-side search (Jun 2026 cross-page filter add-on):
            # when `?q=foo` is provided, narrow the distinct set to
            # values whose string form contains `foo` (case-insensitive
            # substring). The admin's search box debounces and AJAXes
            # here so the user can find values that aren't in the
            # initial top-N render (e.g. userId=7777 on 100k rows
            # where the top 200 only show 1-200).
            q = (qs.get("q") or [""])[0].strip().lower()
            distinct = sorted({p.get(field) for p in DATA["posts"] if field in p},
                             key=lambda x: (x is None, x))
            if q:
                distinct = [v for v in distinct if q in str(v).lower()]
            total = len(distinct)
            truncated = False
            if limit > 0:
                sliced = distinct[offset:offset + limit]
                truncated = (offset + limit) < total
            else:
                sliced = distinct
            body = json.dumps({
                "field": field,
                "count": total,            # total distinct count (after ?q= filter)
                "returned": len(sliced),   # count in this response
                "truncated": truncated,    # True if more values exist
                "q": q,                    # echo the search term (debug)
                "values": sliced,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/posts"):
            self.send_error(404, "Not Found")
            return
        # Parse ?page=1&page_size=10 (real APIs use these names; also
        # accept ?_page and ?_limit for JSONPlaceholder-shape compat).
        # parse_qs always returns a list (empty if key missing) — we
        # can't use .get(name, default) to provide a default.
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        def _first(name, fallback):
            v = qs.get(name)
            return v[0] if v else fallback
        def _all(name):
            return qs.get(name, [])
        page = int(_first("page", _first("_page", "1")))
        limit = int(_first("page_size", _first("_limit", "10")))

        # Server-side filter (Jun 2026 cross-page filter). Each filter
        # param narrows the dataset BEFORE pagination so the API
        # returns only matching rows. Multi-value params (e.g. body=A&body=B)
        # are OR-joined. The returned X-Total-Count reflects the
        # FILTERED size so the admin paginator shows the right page
        # count for the filtered set.
        filtered = DATA["posts"]
        # userId: exact integer match
        userId = _first("userId", None)
        if userId is not None:
            try:
                uid = int(userId)
                filtered = [p for p in filtered if p["userId"] == uid]
            except ValueError:
                pass  # ignore non-integer; pass-through
        # title: exact string match
        title = _first("title", None)
        if title is not None:
            filtered = [p for p in filtered if p["title"] == title]
        # body: OR-equals across multiple values (multi-select)
        body_filters = _all("body")
        if body_filters:
            filtered = [p for p in filtered if p["body"] in body_filters]
        # id: exact match (for direct-link / detail page jumping)
        id_filter = _first("id", None)
        if id_filter is not None:
            try:
                fid = int(id_filter)
                filtered = [p for p in filtered if p["id"] == fid]
            except ValueError:
                pass

        # Server-side search (Jun 2026 cross-page q): substring match
        # across title + body (and id/userId as strings for convenience).
        # Without this, the framework's client-side search only sees the
        # current 50 rows of page 1 — searching for a long unique string
        # like 'eaque eius eligendi enim #5555' (which appears on exactly
        # one row, possibly on a different page after server-side sort)
        # returns 0 results.
        # Apply AFTER filter, AFTER sort, BEFORE pagination so the
        # matching row ends up on page 1 if it exists.
        q = _first("q", "").strip()
        if q:
            ql = q.lower()
            def _matches(item):
                # Search across all string fields. id/userId are
                # searchable as strings so '?q=5555' matches id=5555.
                return any(
                    ql in str(v).lower()
                    for v in item.values()
                    if isinstance(v, (str, int, float))
                )
            filtered = [p for p in filtered if _matches(p)]

        # Server-side sort (Jun 2026 cross-page sort): apply AFTER
        # filter and BEFORE pagination so the slice_ is in the right
        # order. Without this, the admin client-side sorts the current
        # 50 rows but page 1 sort + page 2 sort is meaningless (rows
        # arrive in API's default order, not the sort key).
        #
        # Query name parity: real APIs (JSONPlaceholder, GitHub, etc.)
        # use `_sort` / `_order`; some use `sort` / `order`. Accept
        # both so the admin doesn't have to know the convention.
        sort_field = _first("_sort", _first("sort", None))
        sort_order = _first("_order", _first("order", "asc")).lower()
        if sort_field and sort_field in ("id", "userId", "title", "body"):
            reverse = sort_order == "desc"
            # Sort key: None last (per SQL convention), then natural
            # ordering. For string fields use lower() for case-
            # insensitive sort (matches what most users expect from
            # an admin UI; native Python sort is case-sensitive and
            # would put "Zoo" before "apple").
            def _sort_key(p):
                v = p.get(sort_field)
                if v is None:
                    return (1, "")
                if isinstance(v, (int, float)):
                    return (0, v)
                return (0, str(v).lower())
            filtered = sorted(filtered, key=_sort_key, reverse=reverse)

        total = len(filtered)
        start = (page - 1) * limit
        end = start + limit
        slice_ = filtered[start:end]

        body = json.dumps(slice_).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # X-Total-Count = filtered dataset size, so the admin paginator
        # can render the right number of pages for the FILTERED set
        # (e.g. ?userId=1 on 100k rows → X-Total-Count: 10, not 100_000).
        # Without this, the paginator would always show 2000 pages
        # even when only 10 rows match the filter.
        self.send_header("X-Total-Count", str(total))
        self.send_header("Access-Control-Expose-Headers", "X-Total-Count")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--rows", type=int, default=100_000,
                        help="Number of fake posts to generate")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    t0 = time.perf_counter()
    DATA["posts"] = build_dataset(args.rows)
    dt = time.perf_counter() - t0

    print(f"Built {args.rows:,} rows in {dt:.2f}s "
          f"({len(DATA['posts']) * 200 // 1024} KB est.)")

    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"Mock server listening on http://{args.host}:{args.port}")
    print(f"  Try: curl 'http://{args.host}:{args.port}/posts?_page=1&_limit=10'")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
