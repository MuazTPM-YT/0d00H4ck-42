# Schema requests

Migrations have one owner (Muaz) so four people never write clashing Alembic heads.
Need a new table, column, constraint or status value? Add a request below and ping Muaz.

## How

1. Copy the template to the bottom of this file in your feature branch.
2. Open a PR with only that change, or mention it in your feature PR.
3. Muaz edits the model, writes the migration (`alembic revision --autogenerate`, then checks it by
   hand), and merges it to `main`.
4. Rebase your branch on `main`, run `make migrate`.

Do not edit `backend/alembic/versions/` yourself.

## Template

```
### <short title>
- Requested by: <name>, <date>
- Module: <module>
- Change: <table.column type, constraint, or new status value>
- Why: <requirement number and one line>
- Nullable / default for existing rows: <answer>
- Status: requested | done in <migration file>
```

## Requests

### Shade override on dispatch
- Requested by: Ashil, 2026-10-10
- Module: dispatch
- Change: `dispatches.shade_override_reason TEXT NULL`, `dispatches.shade_override_by INT NULL FK users`
- Why: D1 / invariant 7. Today the override is an `audit_log` row (`action = shade_override`) that the service reads back as state.
- Nullable / default for existing rows: nullable, NULL
- Status: requested

### Wage run paid date
- Requested by: Ashil, 2026-10-10
- Module: finance
- Change: `wage_runs.paid_at TIMESTAMPTZ NULL`, CHECK `status <> 'paid' OR paid_at IS NOT NULL`
- Why: R23 cash basis. Today paid wages are dated by `period_end`.
- Nullable / default for existing rows: nullable; backfill paid runs with `period_end`
- Status: requested

### GST rate in settings
- Requested by: Ashil, 2026-10-10
- Module: core (config), used by finance
- Change: `Settings.gst_pct: Decimal = 5` (env `GST_PCT`), plus a line in `.env.example`
- Why: R19, "GST at a configurable rate". Today it is `finance.service.GST_PCT`.
- Nullable / default for existing rows: n/a
- Status: requested

### Not schema, for Muaz: nav, attention items, one test
- Requested by: Ashil, 2026-10-10
- Change 1: add `supervisor` to the roles of `/dispatch/[id]` in `frontend/src/nav.ts`, so a supervisor can open the dispatch and post the shade override from the screen. The API already allows it; today only the owner can do it from the UI.
- Change 2: `analytics.attention_items(db, Role.dispatch)` can call `dispatch.corner_check(db)` to list forgotten rolls as attention items.
- Change 3: `tests/test_errors.py::test_stub_is_501_in_error_shape` used the tracking stub, which is now real, so it fails. It should point at another stub, e.g. `GET /api/orders/{id}/yarn-requirement` (calls `inventory.free_stock`).
- Status: requested
