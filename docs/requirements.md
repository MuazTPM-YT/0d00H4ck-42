# Requirements

From the Textile Manufacturing System problem statement (Everest Textile Mills).
Labels: **Core** first, then **Expected**, then **Stretch**. No Stretch work before every Core item
works end to end (UI, API, DB, validation).

Status: `todo` = not started, `schema` = tables and constraints exist, `partial` = some of
UI/API/logic done, `done` = UI + API + DB + validation + test.

## Scene 1: yarn arrives at the gate

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R1 | Core | Record a yarn receipt (GRN): supplier, yarn type, colour, kg, unit cost, optional order | Ammaar | `/store/receive` | `receipts`, `yarn_batches`, `stock_moves` | done: QR scan, expected vs actual, quarantine on mismatch, tests |
| R2 | Core | Live raw material stock per yarn type and colour | Ammaar | `/store/stock` | `stock_moves`, `yarn_items` | done: ledger sums, live via SSE `stock` |
| R3 | Core | Low-stock warning against per-item reorder level, on the dashboard | Ammaar | `/store`, `/owner` | `yarn_items.reorder_level_kg` | partial: `/store` done (projected free vs reorder, live); `/owner` card needs Muaz to call `GET /api/inventory/stock/warnings` |
| R4 | Core | On a new order, show whether yarn covers it and the shortfall | Ammaar | `/orders/new` | `fabric_recipe`, `stock_moves` | done: live needed/free/short panel, to-buy list |
| R5 | Expected | Reserve yarn so two orders cannot claim the same stock | Ammaar | `/orders`, `/orders/new` | `reservations` | done: row-locked, best-fit lot, concurrency test. `OrderYarnPanel` ready for `/orders/[id]` |

## Scene 2: the production floor

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R6 | Core | Machines with type and status (running, idle, breakdown, maintenance) | Muaz | `/masters/machines`, `/floor` | `machines`, `machine_events` | done |
| R7 | Core | Assign an order stage to a machine; show which order is on which machine and progress | Muaz | `/floor/work-orders` | `work_orders`, `production_logs` | done |
| R8 | Core | Live floor board: each machine's job, status, output today. No reload. | Muaz | `/floor` | `machine_events`, `production_logs` | done |
| R9 | Expected | Breakdowns with reason and downtime; shifts and workers on machines | Muaz | `/floor`, `/floor/crew` | `machine_events`, `crew_assignments` | done |

## Scene 3: quality check

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R10 | Core | Each roll has a unique ID linked to order, machine, shift | Razan | `/qc/rolls/[id]` | `rolls` | schema |
| R11 | Core | QC per roll: pass, rework, reject, with defect type | Razan | `/qc/rolls/[id]` | `qc_checks` | schema |
| R12 | Core | Queue of rolls waiting for QC; pass/fail summary | Razan | `/qc` | `rolls`, `qc_checks` | partial: `GET /api/quality/rolls?status=awaiting_qc` |
| R13 | Expected | Defect analysis by machine and by order | Razan | `/qc`, `/insights` | `qc_checks`, `rolls` | todo |

## Scene 4: a buyer asks about their order

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R14 | Core | Order status derived from data: Confirmed → In Production (stage) → QC → Ready → Dispatched | Ashil | `/orders/[id]` | derived | todo |
| R15 | Core | Order detail page and a read-only buyer tracking link (token, no login) | Ashil | `/orders/[id]`, `/track/[token]` | `orders.tracking_token` | partial: route + token lookup, `order_stage` stub |

## Scene 5: dispatch

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R16 | Core | Finished goods stock: rolls passed and not dispatched | Ashil | `/stock/finished` | `rolls` | schema |
| R17 | Core | Dispatch: pick rolls for an order, vehicle details, quantity check | Ashil | `/dispatch/[id]` | `dispatches`, `dispatch_rolls` | schema |
| R18 | Core | A roll can never be dispatched twice (DB constraint) | Ashil | `/dispatch/[id]` | `dispatch_rolls.roll_id` UNIQUE | schema: constraint in place |
| R19 | Core | Invoice from dispatched rolls, matching quantities and rates | Ashil | `/finance/invoices` | `invoices`, `invoice_lines` | schema |

## Scene 6: month-end books

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R20 | Core | Attendance per shift (Muaz) and wages from it (Ashil) | Muaz, Ashil | `/floor/crew`, `/finance/wages` | `attendance`, `wage_runs`, `wage_lines` | partial: attendance capture done (Muaz), wages todo (Ashil) |
| R21 | Core | Cost per order: yarn + labour + machine, rule stated in the UI | Ashil | `/orders/[id]`, `/finance/month` | many | todo |
| R22 | Core | Production per machine for a period | Muaz | `/owner` | `production_logs` | schema |
| R23 | Core | Monthly profit: payments and invoices vs yarn bills and wages | Ashil | `/finance/month` | `invoices`, `payments`, `receipts`, `wage_lines`, `expenses` | schema |
| R24 | Expected | Buyer payments against invoices; outstanding receivables | Ashil | `/finance/payments` | `payments` | schema |
| R25 | Stretch | Export reports (CSV or PDF) | Ashil | finance pages | none | todo |

## Cross-cutting

| # | Label | Requirement | Owner | Status |
|---|---|---|---|---|
| R26 | Core | Roles: owner, store, supervisor, QC, dispatch, accounts, sales. Server enforces per endpoint. | Muaz (auth), every owner for their routes | partial: login, `require_roles`, role menus done |
| R27 | Expected | Activity log on orders and rolls | Muaz (`audit_log`), every owner writes rows | partial: `audit.record` done, used by masters and work orders |
| — | Core | Masters: suppliers, buyers, yarn items, fabric types, machines, workers, shifts | Muaz | done: CRUD API, validation, screens, tests |

## Differentiators

Start only after the Core items above work. Detail in `.claude/skills/odoo-hackathon-finale/references/differentiators.md`.

| # | Feature | Owner | Status |
|---|---|---|---|
| D1 | Lot continuity and shade-safe dispatch (one shade band per dispatch) | Razan (shade at QC), Ashil (dispatch rule) | schema: `rolls.shade_band`, `qc_checks.pass_has_shade` |
| D2 | Delivery risk early warning (on track / at risk / late) | Muaz | stub: `analytics.delivery_estimate` |
| D3 | Roll genealogy and root cause (machine, shift, supplier) | Razan | schema: `roll_batches`; stub: `quality.roll_trace` |
| D4 | True cost per order (FIFO yarn, labour, machine, rework) | Ashil | stub: `finance.order_cost` |
