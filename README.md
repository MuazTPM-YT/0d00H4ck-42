# Everest Textile Mills

Yarn to dispatch on one ledger. Built by Team 42 (HashMaps) for the Odoo x NMIT Hackathon 2026.

A mid-size mill runs on notebooks, walks the floor to find machine status, writes QC slips on
paper and answers buyers by phone. This app replaces that with one local system: yarn receipts,
live stock, the production floor, roll QC, dispatch, invoices, attendance and month-end profit.
It runs fully on the mill's own machine. No cloud, no internet needed.

## Run it (fresh clone)

Needs: Docker, [uv](https://docs.astral.sh/uv/), Node 20+ with npm, `make`.

```sh
make install          # creates .env with random secrets, installs backend + frontend deps
make db-up migrate seed
make dev              # API on :8000, web on :3000. Ctrl+C stops both.
```

Open http://localhost:3000. Log in as any role: `<role>@everest.local` / `demo1234`.
Roles: `owner`, `store`, `supervisor`, `qc`, `dispatch`, `accounts` (accounts and sales, one desk).

API docs: http://localhost:8000/docs.

| Command | What it does |
|---|---|
| `make install` | `.env` from `.env.example` (random `POSTGRES_PASSWORD`, `JWT_SECRET`), `uv sync`, `npm ci` |
| `make db-up` / `make db-down` | Start / stop Postgres 16 in Docker on `127.0.0.1:${DB_PORT}` (default 5435) |
| `make migrate` | `alembic upgrade head` |
| `make seed` | Demo data: masters, 6 users, at least one row in every status. Safe to run twice. |
| `make seed-big` | **Wipes the dev DB.** Mill-scale masters (43 suppliers, 155 buyers, 224 workers, 42 yarn items; the same 10 machines), then 60 simulated days through the real services: ~2,200 rolls, ~230 dispatches and invoices, then monthly wage runs and running costs. About 3 min. |
| `make dev` | FastAPI with reload + Next dev server |
| `make dev-https` | Same, web over HTTPS (self-signed) so tablets on the LAN can scan labels with the camera |
| `make test` | pytest against a separate `everest_test` database |
| `make lint` | ruff check, ruff format check, `tsc --noEmit` |

Port 5435 busy? Set `DB_PORT` in `.env`.

## Tech stack, and why

| Layer | Choice | Why |
|---|---|---|
| Database | PostgreSQL 16 (local, Docker) | Same DB Odoo runs on. Real constraints (CHECK, partial UNIQUE, FK) guard the data. |
| Backend | FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 | Typed request validation, auto OpenAPI docs, migrations in git. |
| Auth | bcrypt + JWT in an httpOnly cookie (Bearer header also accepted) | Browser never sees the token. Scanners, tests and `/docs` use the header. |
| Live updates | Server-Sent Events | One-way "this changed" push is all we need. Simpler than WebSockets, works through the Next proxy. |
| Frontend | Next.js 15 (client pages), TanStack Query, Tailwind 4, shadcn/ui | Next only serves the UI and proxies `/api` to FastAPI, so one origin and no CORS. |
| Fonts, icons | IBM Plex Sans and Mono, Source Serif 4 (self-hosted by `next/font` at build), lucide-react bundled | Readable at small sizes, one industrial family. Runs offline. |

## Features

Status of each requirement: [docs/requirements.md](docs/requirements.md).

- Yarn receiving with GRN, supplier lot, quarantine, approval and a stock ledger (`stock_moves`).
- Yarn requirement per order from fabric recipe (metres, width, GSM, process loss).
- Floor board: machines, work orders per stage, live status over SSE.
- Rolls with a unique code linked to order, loom, shift, weaver and yarn batches. QC queue with scan box, pass, rework,
  reject, shade band, 4-point defect score, full roll trace and defect analysis by loom and order.
- Buyer tracking link (no login) showing the order stage, derived from real data.
- Shade-safe dispatch: a roll can never be dispatched twice (DB constraint).
- Invoices from dispatched rolls, payments, attendance-based wages, cost per order, month-end profit.
- Role-based menus and server-side role checks on every endpoint. Audit log on key records.

## Project layout

```
backend/app/core/        config, db, auth deps, errors, audit, codes, idempotency, SSE, pagination
backend/app/modules/<m>/ models.py, schemas.py, service.py, router.py   (one folder per module)
backend/alembic/         migrations
backend/tests/           pytest
frontend/src/app/        one folder per route (Next App Router)
frontend/src/features/   screen code per module
frontend/src/components/ design system (layout + shadcn ui)
frontend/src/nav.ts      every route, its roles and owner: drives sidebar, breadcrumbs, page guard
scripts/seed.py          demo data
docs/                    architecture, ERD, contracts, requirements, decisions
```

## Docs

- [Architecture](docs/architecture.md): how a request flows, layers, live updates.
- [ER diagram](docs/erd.md): every table.
- [Contracts](docs/contracts.md): rules every module follows, status maps, shared service signatures.
- [Requirements](docs/requirements.md): R1 to R27 with owner and status.
- [Decisions](docs/decisions.md) and [assumptions](docs/assumptions.md).
- [Schema requests](docs/schema-requests.md): how to ask for a DB change.

## Team

| Member | GitHub | Owns |
|---|---|---|
| Muaz Ismail Mohammed | @MuazTPM-YT | Core, DB, auth, masters, production, workforce, analytics, seed |
| Ammaar | @ammaartech | Inventory (yarn store), orders |
| The Razan | @razancodes | Design system, quality (QC) |
| Mohammed Ashil (lead) | @Ashil07 | Tracking, dispatch, finance |

Exact paths per owner: [CODEOWNERS](CODEOWNERS).

## License

MIT. See [LICENSE](LICENSE).
