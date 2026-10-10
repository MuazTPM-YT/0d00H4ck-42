# Decisions

One line of context, the choice, and why. Newest at the bottom.

| # | Decision | Why | Rejected |
|---|---|---|---|
| 1 | Local PostgreSQL 16 in Docker | Odoo runs on Postgres. Real CHECK, partial UNIQUE and FK constraints. Works offline. | SQLite (weaker constraints), Firebase / hosted Supabase (cloud, no backend skill shown) |
| 2 | FastAPI + SQLAlchemy 2 + Alembic | Typed validation, OpenAPI docs for free, migrations in git. Team knows Python. | Django (heavier admin we would not use) |
| 3 | Next.js 15, client pages only, `/api` rewritten to FastAPI | One origin: no CORS, httpOnly cookie works. Business logic stays in one place (FastAPI). | Server actions or Next API routes (two backends), Vite SPA (needs CORS) |
| 4 | JWT in httpOnly cookie, Bearer header also accepted | Browser JS never sees the token. Scanners, tests and `/docs` use the header. | localStorage token (XSS can read it) |
| 5 | Owner role = admin, passes every role check | The mill owner must see everything. Sidebar still shows only owner screens. | Separate admin role |
| 6 | Stock as an append-only ledger (`stock_moves` with from/to location) | History, audit, availability and low-stock all come from one table. No counter drift. | Mutable `qty` column per item |
| 7 | Status columns as VARCHAR + CHECK, not native PG enums | Adding a status is a plain migration, no `ALTER TYPE`. | Native PG enum |
| 8 | Money as BIGINT paise, quantities as NUMERIC(12,3) | No float rounding. | float, NUMERIC rupees |
| 9 | Buyer-facing order stage derived, never stored | A typed status drifts from reality. | `orders.stage` column |
| 10 | Status changes only through `check_transition()` maps | Illegal moves rejected on the server with 409, not only hidden in the UI. | Ad hoc `if` checks |
| 11 | Codes from `code_sequences` with row-locked upsert | Human-readable codes (`WO-000001`), no duplicates, rollback leaves no gap. | DB sequences (gaps), UUIDs (not readable on a slip) |
| 12 | `idempotency_keys` table | A double scan or a machine feed retry must not post twice. Generic for every scan endpoint. | Per-table unique keys only |
| 13 | Server-Sent Events, payload is only `{topic, type, id}` | One-way push is enough. Client refetches through the API, so role checks still apply. | WebSockets (two-way, more code), polling (slow, wasteful) |
| 14 | In-process SSE fan-out, one uvicorn worker | Enough for one mill. | PG `LISTEN/NOTIFY` (add when more workers needed) |
| 15 | No form library, no zod on the frontend | Native HTML validation for instant feedback, server field errors are the authority. Less to explain. | react-hook-form + zod |
| 16 | System font stack, bundled icons | Offline. | Google Fonts at runtime |
| 17 | Every dependency pinned to a minor version, lockfiles committed, resolver date guard (`exclude-newer`, npm `before`) | Supply-chain safety: no release from the last 14 days. | Caret ranges |
| 18 | Commit format `[TAG] module: short message` (Odoo style) | Matches how Odoo writes commits. Judges read it daily. | Conventional Commits |
| 19 | One folder per module (`models`, `schemas`, `service`, `router`) and `CODEOWNERS` per path | Four people work in parallel with few merge conflicts. Ownership is visible. | Layer-first folders |
| 20 | Deactivate masters (`active = false`), never delete | Old orders and rolls keep pointing at valid rows. | Hard delete |
