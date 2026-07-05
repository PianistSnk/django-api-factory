"""Local mock REST server for the example project.

Mimics JSONPlaceholder shape (id / userId / title / body) so the same
APIAdmin code path works. Supports `?_page=N&_limit=M` pagination.

Usage:
    python examples/local-mock/mock_server.py --port 8200 --rows 100000
    curl 'http://127.0.0.1:8200/posts?_page=1&_limit=10'
"""

import argparse
import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Fixed seed gives identical data across runs, which helps benchmarking.
random.seed(42)

# Pre-built dataset — built once at startup, served from memory.
# Tweak ROWS via --rows (1w / 10w / 100w). User count scales with row count.
DATA = {"posts": [], "customers": []}

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
    # Keep enough templates that sorted pages show multiple visible groups
    # even when each page contains many rows.
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
    "quia et suscipit suscipit recusandae consequuntur expedita "
    "et cum reprehenderit molestiae",
    "est rerum tempore vitae sequi sint nihil reprehenderit dolor quia",
    "et iusto sed quo iure voluptatem occaecati omnis eligendi "
    "aut ad voluptatem doloribus",
    "sint et ea voluptas illo aperiam quaerat fuga voluptas reprehenderit amet",
    "in voluptate sit ea ut autem non aut corporis",
    "qui ratione porro omnis quia minus",
    "consectetur adipisci amet sit fugit sunt voluptatem",
    "voluptatem repellat sit provident aperiam voluptatem",
    "rerum voluptatem consequatur ut facere",
    "architecto et voluptas sint sit amet nemo aut consequuntur",
    # Keep this aligned with TITLE_TEMPLATES for visual variety.
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


FIRST_NAMES = [
    "Ava", "Noah", "Mia", "Liam", "Emma", "Oliver", "Sophia", "Elijah",
    "Isabella", "Lucas", "Amelia", "Mason", "Harper", "Logan", "Evelyn",
    "Ethan", "Luna", "James", "Aria", "Benjamin",
]

LAST_NAMES = [
    "Chen", "Smith", "Johnson", "Wang", "Brown", "Garcia", "Miller",
    "Davis", "Wilson", "Taylor", "Anderson", "Thomas", "Moore", "Martin",
    "Lee", "Clark", "Lewis", "Young", "Hall", "Allen",
]

CITIES = [
    "New York", "San Francisco", "Seattle", "Austin", "Chicago", "Boston",
    "Los Angeles", "Denver", "Atlanta", "Miami", "London", "Paris",
    "Berlin", "Tokyo", "Singapore", "Sydney", "Toronto", "Dublin",
    "Amsterdam", "Hong Kong",
]

COUNTRIES = [
    "US", "US", "US", "US", "US", "US", "US", "US", "US", "US",
    "UK", "FR", "DE", "JP", "SG", "AU", "CA", "IE", "NL", "HK",
]

REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
INDUSTRIES = [
    "FinTech", "Healthcare", "Retail", "Manufacturing", "Education",
    "Gaming", "Energy", "Logistics", "Media", "SaaS",
]
SEGMENTS = ["enterprise", "mid-market", "smb", "public-sector", "education"]
PLANS = ["free", "starter", "growth", "business", "enterprise"]
STATUSES = ["active", "trial", "paused", "churned", "delinquent"]
SOURCES = ["web", "partner", "event", "referral", "marketplace", "sales"]
CHANNELS = ["self-serve", "inside-sales", "field-sales", "reseller"]
DEPARTMENTS = ["Finance", "Operations", "IT", "Marketing", "Sales", "HR"]
ROLES = ["Admin", "Buyer", "Analyst", "Manager", "Developer", "Executive"]
RISK_LEVELS = ["low", "medium", "high", "critical"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
SLA_TIERS = ["bronze", "silver", "gold", "platinum"]
CURRENCIES = ["USD", "EUR", "JPY", "SGD", "AUD", "CAD", "GBP"]


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


def build_customer_dataset(n_customers: int) -> list:
    """Generate a wide external-API-style customer dataset.

    This intentionally has many fields so the admin can exercise dynamic
    columns, cross-page filters, server-side sort, and pagination against
    something closer to an enterprise CRM / customer-360 endpoint.
    """
    customers = []
    for i in range(1, n_customers + 1):
        city_idx = i % len(CITIES)
        region = REGIONS[i % len(REGIONS)]
        plan = PLANS[i % len(PLANS)]
        status = STATUSES[i % len(STATUSES)]
        risk_level = RISK_LEVELS[(i * 7) % len(RISK_LEVELS)]
        currency = CURRENCIES[i % len(CURRENCIES)]
        signup_month = (i % 12) + 1
        signup_day = (i % 28) + 1
        last_login_day = ((i * 3) % 28) + 1
        updated_hour = i % 24
        total_orders = (i * 11) % 500
        total_spend = round(((i * 1379) % 750_000) / 10, 2)
        lifetime_value = round(total_spend * (1.2 + ((i % 9) / 10)), 2)
        churn_probability = round(((i * 37) % 1000) / 1000, 3)
        credit_score = 300 + ((i * 17) % 550)
        is_active = status in {"active", "trial", "paused"}
        tags = "\u3001".join([
            SEGMENTS[i % len(SEGMENTS)],
            plan,
            "renewal" if i % 3 else "expansion",
        ])
        first_name = FIRST_NAMES[i % len(FIRST_NAMES)]
        last_name = LAST_NAMES[(i * 3) % len(LAST_NAMES)]
        customers.append({
            "id": i,
            "customerNo": f"CUST-{i:06d}",
            "accountId": ((i - 1) // 5) + 1,
            "customerName": f"{first_name} {last_name}",
            "email": f"customer{i}@example-{i % 250}.com",
            "phone": f"+1-555-{i % 1000:03d}-{i % 10000:04d}",
            "company": f"{INDUSTRIES[i % len(INDUSTRIES)]} Labs {((i - 1) // 20) + 1}",
            "industry": INDUSTRIES[i % len(INDUSTRIES)],
            "companySize": 10 + ((i * 29) % 20_000),
            "country": COUNTRIES[city_idx],
            "region": region,
            "city": CITIES[city_idx],
            "segment": SEGMENTS[i % len(SEGMENTS)],
            "plan": plan,
            "status": status,
            "source": SOURCES[i % len(SOURCES)],
            "channel": CHANNELS[i % len(CHANNELS)],
            "ownerId": ((i - 1) % 300) + 1,
            "priority": PRIORITIES[i % len(PRIORITIES)],
            "riskLevel": risk_level,
            "creditScore": credit_score,
            "totalOrders": total_orders,
            "totalSpend": total_spend,
            "lifetimeValue": lifetime_value,
            "churnProbability": churn_probability,
            "balance": round(total_spend * (((i % 11) - 5) / 100), 2),
            "currency": currency,
            "isActive": is_active,
            "signupDate": f"2021-{signup_month:02d}-{signup_day:02d}",
            "lastLogin": f"2026-06-{last_login_day:02d} {updated_hour:02d}:30:00",
            "updatedAt": f"2026-07-{signup_day:02d}T{updated_hour:02d}:15:00Z",
            "department": DEPARTMENTS[i % len(DEPARTMENTS)],
            "role": ROLES[i % len(ROLES)],
            "slaTier": SLA_TIERS[i % len(SLA_TIERS)],
            "contractMonths": 1 + ((i * 5) % 60),
            "renewalMonth": ((i * 2) % 12) + 1,
            "tags": tags,
            "notes": f"{status} {plan} customer in {CITIES[city_idx]} #{i}",
        })
    return customers


def _first_query(qs, name, fallback):
    value = qs.get(name)
    return value[0] if value else fallback


def _csv_values(qs, name):
    values = []
    for raw in qs.get(name, []):
        values.extend(value for value in raw.split(",") if value != "")
    return values


def _filter_and_sort_rows(rows, qs):
    if not rows:
        return rows
    field_names = set(rows[0])
    reserved = {
        "_page", "_limit", "page", "page_size",
        "_sort", "_order", "sort", "order",
        "q", "ajax_distinct", "field", "limit", "offset", "resource",
    }
    filtered = rows
    for field_name in field_names:
        if field_name in reserved:
            continue
        filters = set(_csv_values(qs, field_name))
        if filters:
            filtered = [
                row for row in filtered
                if str(row.get(field_name, "")) in filters
            ]

    q = _first_query(qs, "q", "").strip().lower()
    if q:
        filtered = [
            row for row in filtered
            if any(q in str(value).lower() for value in row.values())
        ]

    sort_field = _first_query(qs, "_sort", _first_query(qs, "sort", None))
    sort_order = _first_query(qs, "_order", _first_query(qs, "order", "asc")).lower()
    if sort_field and sort_field in field_names:
        reverse = sort_order == "desc"

        def _sort_key(row):
            value = row.get(sort_field)
            if value is None:
                return (1, "")
            if isinstance(value, (int, float)):
                return (0, value)
            return (0, str(value).lower())

        filtered = sorted(filtered, key=_sort_key, reverse=reverse)
    return filtered


class MockHandler(BaseHTTPRequestHandler):
    """GET /posts?_page=N&_limit=M → JSON list of posts."""

    def log_message(self, fmt, *args):
        # Log every GET with response size + handler time.
        import time
        if not hasattr(self, "_t0"):
            self._t0 = time.perf_counter()
        dt_ms = (time.perf_counter() - self._t0) * 1000
        sys.stderr.write(f"[mock] {self.command} {self.path} ({dt_ms:.1f}ms)\n")
        sys.stderr.flush()

    def do_GET(self):
        # Envelope-shape endpoints. APIModel.parse_response supports
        # 4 industry-standard shapes. Hit each one with a
        # matching admin class to verify the unwrap hook handles all
        # four correctly. Same data as /posts, different envelope.
        # 4 alias paths, each returning a different envelope shape:
        #   /posts-bare     → bare list                [{...}, ...]
        #   /posts-data     → {"data": [...]}          (Laravel/internal)
        #   /posts-items    → {"items": [...]}         (older internal)
        #   /posts-results  → {"results": [...]}       (DRF default)
        if self.path.startswith(("/posts-bare", "/posts-data",
                                  "/posts-items", "/posts-results")):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            page = int((qs.get("page") or qs.get("_page") or ["1"])[0])
            limit = int((qs.get("page_size") or qs.get("_limit") or ["10"])[0])
            sliced = DATA["posts"][(page - 1) * limit: page * limit]
            shape = parsed.path.lstrip("/")  # e.g. "posts-data" (no query)
            if shape == "posts-bare":
                body = json.dumps(sliced).encode("utf-8")
            elif shape == "posts-data":
                body = json.dumps({"data": sliced}).encode("utf-8")
            elif shape == "posts-items":
                body = json.dumps({"items": sliced}).encode("utf-8")
            elif shape == "posts-results":
                body = json.dumps({"count": len(DATA["posts"]),
                                   "next": None, "previous": None,
                                   "results": sliced}).encode("utf-8")
            else:
                self.send_error(404, f"Unknown envelope shape: {shape!r}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Total-Count", str(len(DATA["posts"])))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
        # /distinct?field=X[&limit=N&offset=M]. Returns distinct values
        # for a field across the entire
        # dataset, optionally paginated. Without this, ?userId= dropdown
        # on 100k rows / 200 per page only shows 200 userIds, not the
        # real 10_000. With limit=N, the response stays small (N values)
        # so the admin HTML doesn't explode to 41MB.
        if self.path.startswith("/distinct"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            resource = (qs.get("resource") or qs.get("dataset") or ["posts"])[0]
            rows = DATA.get(resource)
            if rows is None:
                self.send_error(400, f"Unknown ?resource={resource!r}")
                return
            field = (qs.get("field") or [None])[0]
            if not field:
                self.send_error(400, "Missing ?field=<name>")
                return
            limit = int((qs.get("limit") or [None])[0] or 0)
            offset = int((qs.get("offset") or [None])[0] or 0)
            # Server-side search: when `?q=foo` is provided, narrow the distinct set to
            # values whose string form contains `foo` (case-insensitive
            # substring). The admin's search box debounces and AJAXes
            # here so the user can find values that aren't in the
            # initial top-N render (e.g. userId=7777 on 100k rows
            # where the top 200 only show 1-200).
            q = (qs.get("q") or [""])[0].strip().lower()
            distinct = sorted(
                {p.get(field) for p in rows if field in p},
                key=lambda x: (
                    x is None,
                    x if isinstance(x, (int, float)) else str(x).lower(),
                ),
            )
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
        # /customers is a wide, external-API-style endpoint: 35+ fields,
        # 100k rows, server-side pagination/filter/sort/search. It exists
        # specifically to stress-test django-api-factory against a much
        # wider schema than JSONPlaceholder posts.
        if self.path.startswith("/customers"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            page = int(_first_query(qs, "page", _first_query(qs, "_page", "1")))
            limit = int(_first_query(qs, "page_size", _first_query(qs, "_limit", "10")))
            filtered = _filter_and_sort_rows(DATA["customers"], qs)
            total = len(filtered)
            start = (page - 1) * limit
            end = start + limit
            slice_ = filtered[start:end]

            body = json.dumps(slice_).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Total-Count", str(total))
            self.send_header("Access-Control-Expose-Headers", "X-Total-Count")
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
        def _csv_values(name):
            values = []
            for raw in _all(name):
                values.extend(v for v in raw.split(",") if v != "")
            return values
        page = int(_first("page", _first("_page", "1")))
        limit = int(_first("page_size", _first("_limit", "10")))

        # Server-side filter. Each filter
        # param narrows the dataset BEFORE pagination so the API
        # returns only matching rows. Multi-value params (e.g. body=A&body=B)
        # are OR-joined. The returned X-Total-Count reflects the
        # FILTERED size so the admin paginator shows the right page
        # count for the filtered set.
        filtered = DATA["posts"]
        # userId: exact integer match, OR across comma/repeated values.
        user_id_filters = []
        for raw in _csv_values("userId"):
            try:
                user_id_filters.append(int(raw))
            except ValueError:
                pass
        if user_id_filters:
            user_ids = set(user_id_filters)
            filtered = [p for p in filtered if p["userId"] in user_ids]
        # title/body: exact string match, OR across comma/repeated values.
        title_filters = set(_csv_values("title"))
        if title_filters:
            filtered = [p for p in filtered if p["title"] in title_filters]
        body_filters = set(_csv_values("body"))
        if body_filters:
            filtered = [p for p in filtered if p["body"] in body_filters]
        # id: exact match, OR across comma/repeated values.
        id_filters = []
        for raw in _csv_values("id"):
            try:
                id_filters.append(int(raw))
            except ValueError:
                pass
        if id_filters:
            ids = set(id_filters)
            filtered = [p for p in filtered if p["id"] in ids]

        # Server-side search: substring match
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

        # Server-side sort: apply AFTER
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
    DATA["customers"] = build_customer_dataset(args.rows)
    dt = time.perf_counter() - t0

    est_kb = (len(DATA["posts"]) * 200 + len(DATA["customers"]) * 900) // 1024
    print(
        f"Built {args.rows:,} posts + {args.rows:,} customers in {dt:.2f}s "
        f"({est_kb} KB est.)"
    )

    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"Mock server listening on http://{args.host}:{args.port}")
    print(f"  Try: curl 'http://{args.host}:{args.port}/posts?_page=1&_limit=10'")
    print(f"  Wide external API: curl 'http://{args.host}:{args.port}/customers?page=1&page_size=10'")
    print("  4 envelope shapes: /posts-bare /posts-data /posts-items /posts-results")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
