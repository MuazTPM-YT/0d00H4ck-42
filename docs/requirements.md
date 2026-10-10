# Requirements

From the Textile Manufacturing System problem statement (Everest Textile Mills).
Labels: **Core** first, then **Expected**, then **Stretch**. No Stretch work before every Core item
works end to end (UI, API, DB, validation).

Status: `todo` = not started, `schema` = tables and constraints exist, `partial` = some of
UI/API/logic done, `done` = UI + API + DB + validation + test.

## Scene 1: yarn arrives at the gate

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R1 | Core | Record a yarn receipt (GRN): supplier, yarn type, colour, kg, unit cost, optional order | Ammaar | `/store/receive` | `receipts`, `yarn_batches`, `stock_moves` | schema |
| R2 | Core | Live raw material stock per yarn type and colour | Ammaar | `/store/stock` | `stock_moves`, `yarn_items` | schema |
| R3 | Core | Low-stock warning against per-item reorder level, on the dashboard | Ammaar | `/store`, `/owner` | `yarn_items.reorder_level_kg` | schema |
| R4 | Core | On a new order, show whether yarn covers it and the shortfall | Ammaar | `/orders/new` | `fabric_recipe`, `stock_moves` | partial: formula + `GET /api/orders/{id}/yarn-requirement` done, `free_stock` stub |
| R5 | Expected | Reserve yarn so two orders cannot claim the same stock | Ammaar | `/orders/[id]` | `reservations` | schema |

## Scene 2: the production floor

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R6 | Core | Machines with type and status (running, idle, breakdown, maintenance) | Muaz | `/masters/machines`, `/floor` | `machines`, `machine_events` | partial: machine master done |
| R7 | Core | Assign an order stage to a machine; show which order is on which machine and progress | Muaz | `/floor/work-orders` | `work_orders`, `production_logs` | partial: `create_work_orders` done |
| R8 | Core | Live floor board: each machine's job, status, output today. No reload. | Muaz | `/floor` | `machine_events`, `production_logs` | partial: SSE channel done |
| R9 | Expected | Breakdowns with reason and downtime; shifts and workers on machines | Muaz | `/floor`, `/floor/crew` | `machine_events`, `crew_assignments` | schema |

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
| R14 | Core | Order status derived from data: Confirmed → In Production (stage) → QC → Ready → Dispatched | Ashil | `/orders/[id]` | derived | done: `tracking.derive_stage`, tests per seeded order |
| R15 | Core | Order detail page and a read-only buyer tracking link (token, no login) | Ashil | `/orders/[id]`, `/track/[token]` | `orders.tracking_token` | done: order view, public link, token rotate; estimate pending until `analytics.delivery_estimate` |

## Scene 5: dispatch

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R16 | Core | Finished goods stock: rolls passed and not dispatched | Ashil | `/stock/finished` | `rolls` | done: shelf by order, corner check |
| R17 | Core | Dispatch: pick rolls for an order, vehicle details, quantity check | Ashil | `/dispatch/[id]` | `dispatches`, `dispatch_rolls` | done: roll proposal, scan loading, confirm |
| R18 | Core | A roll can never be dispatched twice (DB constraint) | Ashil | `/dispatch/[id]` | `dispatch_rolls.roll_id` UNIQUE | done: constraint + row locks, concurrent test |
| R19 | Core | Invoice from dispatched rolls, matching quantities and rates | Ashil | `/finance/invoices` | `invoices`, `invoice_lines` | done: made at dispatch confirm, printable |

## Scene 6: month-end books

| # | Label | Requirement | Owner | Screen | Tables | Status |
|---|---|---|---|---|---|---|
| R20 | Core | Attendance per shift (Muaz) and wages from it (Ashil) | Muaz, Ashil | `/floor/crew`, `/finance/wages` | `attendance`, `wage_runs`, `wage_lines` | wages done (Ashil); attendance entry is Muaz |
| R21 | Core | Cost per order: yarn + labour + machine, rule stated in the UI | Ashil | `/orders/[id]`, `/finance/month` | many | done: `finance.order_cost`, rule on screen |
| R22 | Core | Production per machine for a period | Muaz | `/owner` | `production_logs` | partial: API + table on `/finance/month` (Ashil); `/owner` view is Muaz |
| R23 | Core | Monthly profit: payments and invoices vs yarn bills and wages | Ashil | `/finance/month` | `invoices`, `payments`, `receipts`, `wage_lines`, `expenses` | done: invoiced + cash basis, drilldown |
| R24 | Expected | Buyer payments against invoices; outstanding receivables | Ashil | `/finance/payments` | `payments` | done |
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
| D1 | Lot continuity and shade-safe dispatch (one shade band per dispatch) | Razan (shade at QC), Ashil (dispatch rule) | dispatch rule done (scan + confirm + override); shade entry at QC is Razan |
| D2 | Delivery risk early warning (on track / at risk / late) | Muaz | stub: `analytics.delivery_estimate` |
| D3 | Roll genealogy and root cause (machine, shift, supplier) | Razan | schema: `roll_batches`; stub: `quality.roll_trace` |
| D4 | True cost per order (FIFO yarn, labour, machine, rework) | Ashil | done: `finance.order_cost` |
