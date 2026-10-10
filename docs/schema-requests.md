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

### One live insight per finding, at the database
- Requested by: Muaz, 2026-10-10
- Module: analytics
- Change: `insights.finding_key VARCHAR(80) NOT NULL DEFAULT ''` and a partial unique index on
  `(kind, entity_type, entity_id, finding_key) WHERE status <> 'resolved'`
- Why: D5. Today the key lives in `facts.key` and an advisory lock prevents duplicates; the index
  would make the database the last guard, like every other invariant.
- Nullable / default for existing rows: default `''`, backfill from `facts->>'key'`
- Status: requested (nice to have, not blocking)
