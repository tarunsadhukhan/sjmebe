# DB & Data Changes — Login Fix (2026-07-15 → 2026-07-16)

Record of every database change made while fixing the login flow
(`notFound()` crash → subdomain validation → portal/admin login working).

**Server:** MySQL `187.127.187.26:3306` (creds: `env/database.env`, user `myroot`)
**Database:** `vowconsole3`

---

## Schema changes

**None.** No tables were created or dropped, and no columns were added,
removed, or altered. All changes below are row data only.

## Data changes — `vowconsole3.con_org_master`

Why: `GET /api/authRoutes/validate-subdomain` only accepts subdomains that
exist in `con_org_master` with `active = 1`. The `sjm` org had no row, so the
frontend `SubdomainGuard` rejected the deployment's own subdomain (fallback
`NEXT_PUBLIC_STATIC_SUBDOMAIN=sjm` on IP/apex access) and the login screen
showed 404 / crashed.

| # | When | Change | By |
|---|------|--------|----|
| 1 | 2026-07-15 | **INSERT** row `con_org_id = 42`: `con_org_name='SJM'`, `con_org_shortname='sjm'`, `active=1`, `con_org_master_status=3`, `created_by=1`, `con_modules_selected='["1","2","3","4","5","6","7","8","9"]'` (other columns NULL/default) | Claude (automated fix) |
| 2 | 2026-07-15 | **UPDATE** row `con_org_id = 41` (formerly `vownjm`): renamed to `con_org_name='SJM'`, `con_org_shortname='sjm'` — this is now the row that validates the `sjm` subdomain | manual (user) |
| 3 | 2026-07-15 | **UPDATE** row `con_org_id = 42`: renamed to `con_org_name='SJMxx'`, `con_org_shortname='sjmxx'` to avoid a duplicate `sjm` shortname | manual (user) |

### Current state (verified 2026-07-16)

```
con_org_id | con_org_name | con_org_shortname | active
41         | SJM          | sjm               | 1
42         | SJMxx        | sjmxx             | 1
```

⚠️ Row 42 (`sjmxx`) is a parked leftover and still `active=1`, so
`sjmxx.<domain>` validates as a real org. Set `active=0` or delete it if
that is not wanted:

```sql
UPDATE vowconsole3.con_org_master SET active = 0 WHERE con_org_id = 42;
```

### Test users referenced (pre-existing, NOT created by this fix)

| Username | Login type | Lands on |
|----------|-----------|----------|
| `njmadmin@vowerp.co.in` | Admin Login | `/dashboardadmin` (user in `vowconsole3`) |
| `testuser@test.in` | Portal Login | `/dashboardportal` (portal user, `user_id=20`) |

---

## Related code changes (context, not DB)

| File | Change |
|------|--------|
| `vowerp3ui/src/components/clientside/SubdomainGuard.tsx` | No more `notFound()` from root layout (Next 16 forbids it) — renders the 404 page inline; reserved `admin` subdomain whitelisted (control desk, never an org row) |
| `vowerp3ui/src/app/layout.tsx` | `<SubdomainGuard>` now wraps `{children}` instead of rendering as a sibling |
| `sjmvowerp3be/src/main.py` | stdout/stderr reconfigured to UTF-8 (`errors='replace'`) — emoji `print()`s in route handlers crashed every request with `UnicodeEncodeError` (cp1252) → 500 on login; CORS middleware moved outermost so 500s carry CORS headers instead of appearing as browser CORS failures |

## Environment note

Port 8000 must be served by `e:\sjm\sjmvowerp3be` (this repo). A second
checkout at `D:\vownextjs\vowerp3be` (DB `3.7.255.145`, different CORS) can
bind the same port simultaneously and intercept requests — two such leftover
processes were killed on 2026-07-15.

## Verification (2026-07-16, automated browser test)

- `GET /api/authRoutes/validate-subdomain?subdomain=sjm` → `{"valid": true}`
- `http://192.168.0.133:3000` login page renders (no 404, no crash)
- Portal login `testuser@test.in` → 200, redirect to `/dashboardportal`, full menu, 0 console errors
- Admin login `njmadmin@vowerp.co.in` → `/dashboardadmin` (verified 2026-07-15)
