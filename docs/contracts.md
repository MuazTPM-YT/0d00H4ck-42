# Contracts

Rules every module follows. If your change breaks one, talk to the module owner first.

## Conventions

- **Layers.** `router.py` (HTTP, schema, role) → `service.py` (rules, transaction) → `models.py`.
  Routers never touch the session beyond passing it on.
- **Transactions.** A route's own service function does the work, writes the audit row, calls
  `db.commit()`, then `events.publish()`. **Shared services never commit.** The caller owns the
  transaction, so a multi-module action commits or rolls back as one.
- **Errors.** Raise `NotFound`, `Conflict`, `Forbidden`, `Unauthorized`, `BadRequest`,
  `Unprocessable` from `app.core.errors`. Pass `field=` when one input is wrong. Every error
  reaches the client as `{"error": {"code", "message", "field"}}`. A stub raising
  `NotImplementedError` returns 501 `not_implemented`.
- **Validation.** Client (instant, inline) → Pydantic schema (authority) → DB constraint (last
  guard). Strip strings, reject empty, positive quantities, real ranges. In a validator, raise
  `FieldError(field, message)` to point at one field.
- **Roles.** Every route has `Depends(get_current_user)` or `Depends(require_roles(...))`. Owner
  is admin and passes every `require_roles` check. `/api/track/{token}` is the only public route.
- **Status changes.** Always `check_transition(MAP, current, new)` from `app.core.states`. Off the
  map = 409 `illegal_transition`. Maps live at the top of each `service.py` and are copied below.
- **Codes.** `next_code(db, prefix)` from `app.core.codes`, in the same transaction. Format
  `WO-000001`. Prefixes: `YB` yarn batch, `RC` receipt, `SO` order, `WO` work order, `R` roll,
  `DN` dispatch, `INV` invoice.
- **Idempotency.** Scan and machine-feed endpoints accept an `idempotency_key` and wrap the work in
  `run_once(db, key, scope, fn)`. A repeat returns the first response.
- **Audit.** `audit.record(db, user_id, action, entity_type, entity_id, reason=None, data=None)` on
  every state change. Same transaction as the change.
- **Lists.** `PageDep` (limit 1 to 200, default 50, offset ≥ 0) and `paginate(db, stmt, page)` →
  `{items, total}`.
- **Units.** Money in BIGINT paise (`rupees_to_paise`, `line_amount_paise`). Quantities as
  `Decimal`, 3 dp (`qty()`). Yarn in kg, fabric in metres. Never mix.
- **Time.** Stored as timestamptz (UTC). Shown in IST by `frontend/src/lib/format.ts`.
- **Enums.** VARCHAR + CHECK via `str_enum()`. Adding a value is a normal migration.
- **Live updates.** After commit, `events.publish(topic, {"type": ..., "id": ...})`. Topics:
  `stock`, `machines`, `orders`, `quality`, `dispatch`, `insights`. Frontend query keys start
  with the topic or module name, so `useSSE()` can invalidate them.
- **Commits.** Odoo format, `[TAG] module: short message`, tags `[ADD] [FIX] [IMP] [REF] [REM]`.
  Branch per feature, PR into `main`. Full rules in `CLAUDE.md`.

## Invariants

1. **Stock is a ledger.** `stock_moves` is append-only. Never UPDATE or DELETE a move. Stock at a
   location = moves in − moves out.
2. **Stock never goes negative** at any location. Checked in the service before the move is written.
3. **Only approved yarn is usable.** Batches in `pending_identification`, `inspection`,
   `quarantined` or `rejected` never count as free stock.
4. **No double reservation.** Reservations ≤ free stock. Lock batch rows (`SELECT ... FOR UPDATE`)
   while reserving.
5. **Recipe shares sum to 100** per fabric type. Checked in the masters schema.
6. **A roll is dispatched at most once, and only after QC pass.** DB: `dispatch_rolls.roll_id`
   UNIQUE. Service: roll status must be `passed`.
7. **One shade band per dispatch** unless a supervisor overrides with a reason (audited).
8. **Buyer-facing order stage is derived** from work orders, rolls and dispatches. It is never
   stored or typed by hand. `orders.status` is only the commercial state.
9. **Invoices come from dispatched rolls.** Lines are copied from rolls, never typed. Invoice status
   follows payments, never set by hand.

## Transition maps

Anything not listed is illegal. Terminal states have no row.

| Entity | From | Allowed to |
|---|---|---|
| Order | `draft` | `confirmed`, `cancelled` |
| | `confirmed` | `cancelled`, `closed` |
| Expected delivery | `open` | `partially_received`, `received`, `cancelled` |
| | `partially_received` | `received`, `cancelled` |
| Receipt | `draft` | `confirmed` |
| Yarn batch | `pending_identification` | `inspection`, `quarantined`, `rejected` |
| | `inspection` | `approved`, `quarantined`, `rejected` |
| | `quarantined` | `approved`, `rejected` |
| | `approved` | `quarantined` |
| Reservation | `active` | `consumed`, `released` |
| Work order | `waiting` | `queued` |
| | `queued` | `running`, `waiting` |
| | `running` | `paused`, `done` |
| | `paused` | `running` |
| Machine | any | any other status (a reported fact; repeating the current one is rejected) |
| Roll | `in_process` | `awaiting_qc` |
| | `awaiting_qc` | `passed`, `rework`, `rejected` |
| | `rework` | `awaiting_qc`, `rejected` |
| | `passed` | `dispatched` |
| Dispatch | `draft` | `loading` |
| | `loading` | `confirmed`, `draft` |
| Invoice | `issued` | `part_paid`, `paid` |
| | `part_paid` | `paid` |
| Wage run | `draft` | `final` |
| | `final` | `paid` |
| Insight | `open` | `acknowledged`, `resolved` |
| | `acknowledged` | `resolved` |

## Shared services

Called across modules. Never commit. Signatures are fixed: change one only after telling every
caller. Status: **done** = implemented and tested, **stub** = raises `NotImplementedError`.

| Function | Owner | Status | Returns |
|---|---|---|---|
| `inventory.stock_on_hand(db, yarn_item_id)` | Ammaar | stub | `Decimal` approved kg in store locations |
| `inventory.free_stock(db, yarn_item_id)` | Ammaar | stub | `Decimal` stock on hand − active reservations |
| `inventory.reserve(db, order_id, user_id)` | Ammaar | stub | `list[Reservation]`; locks batch rows, prefers one supplier lot per component |
| `inventory.issue_to_work_order(db, work_order_id, yarn_batch_id, kg, user_id, source=manual, idempotency_key=None, reason=None)` | Ammaar | stub | `StockMove` store → WIP; over-issue needs `reason`. Must write `reason=issue`, `ref_type="work_order"`, `ref_id=work_order_id`: roll lineage and finish-consume read exactly that |
| `orders.yarn_components(qty_m, fabric, order_colour)` | Ammaar | done | `[{fibre, count, colour, kg_needed}]`; dyed fabric uses `Raw White` yarn |
| `orders.yarn_requirement(db, order_id)` | Ammaar | done (needs `free_stock`) | `[{fibre, count, colour, kg_needed, kg_free, kg_short}]` |
| `production.create_work_orders(db, order_id, user_id)` | Muaz | done | `list[WorkOrder]`, one `waiting` per route stage; second call returns the same set |
| `production.machine_status(db, machine_id)` | Muaz | done | `MachineStatus`, latest event or `off` |
| `production.order_progress(db, order_id)` | Muaz | done | `{stage: {planned, produced, unit}}` |
| `production.create_rework_work_order(db, roll_id, stage, user_id)` | Muaz | done | `WorkOrder` with `roll_id` set; roll must be `rework`; second call returns the open one. Processing the roll on that job sends it back to `awaiting_qc` |
| `quality.roll_trace(db, roll_id)` | Razan | stub | order, loom, shift, weaver, yarn batches + suppliers, QC attempts, events |
| `tracking.order_stage(db, order_id)` | Ashil | stub | derived buyer stage + metres per bucket |
| `dispatch.finished_stock(db, order_id=None, shade_band=None)` | Ashil | stub | `list[Roll]` passed and not dispatched |
| `finance.order_cost(db, order_id)` | Ashil | stub | yarn (FIFO GRN cost) + labour + machine + rework/reject vs revenue |
| `analytics.delivery_estimate(db, order_id)` | Muaz | stub | projected finish, `on_track` / `at_risk` / `late` |
| `analytics.attention_items(db, role)` | Muaz | stub | short to-do list for that role |

Also callable: `workforce.current_shift(db, at)` → `(shift date, Shift)`, night shift belongs to
the date it started; `workforce.crew_on_machine(db, machine_id, at)` → worker id or `None`.

Pure helpers in `app.core.units`: `qty`, `rupees_to_paise`, `line_amount_paise`,
`yarn_kg_for_fabric(metres, width_cm, gsm, loss_pct)`. Yarn kg = metres × width_m × GSM / 1000 /
(1 − loss% / 100).

## API routes today

| Route | Roles |
|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout` | public |
| `GET /api/auth/me` | any logged in |
| `GET /api/health` | public |
| `GET /api/stream?topics=...` | any logged in |
| `GET /api/masters/{suppliers,buyers,yarn-items,fabric-types,machines,workers,shifts}[/{id}]` | any logged in |
| `POST`, `PUT` on the same paths | owner |
| `GET /api/masters/locations` | any logged in |
| `GET /api/inventory/batches` | any logged in |
| `GET /api/orders`, `GET /api/orders/{id}/yarn-requirement` | any logged in |
| `GET /api/production/work-orders`, `/work-orders/open`, `/board`, `/machines/{id}/timeline` | any logged in |
| `POST /api/production/work-orders/{id}/{queue,unqueue,start,move,finish}`, `PUT /api/production/machines/{id}/queue` | supervisor |
| `POST /api/production/machine-events`, `/output`, `/rolls`, `/rolls/{id}/process` | supervisor (machine feeds log in as one) |
| `GET /api/quality/rolls` | any logged in |
| `GET /api/workforce/attendance`, `/crew`, `/current-shift` | supervisor, accounts |
| `PUT /api/workforce/attendance`, `POST /api/workforce/crew`, `POST /api/workforce/crew/{id}/end` | supervisor |
| `GET /api/dispatch/dispatches` | dispatch, accounts |
| `GET /api/finance/invoices` | accounts |
| `GET /api/analytics/insights` | supervisor |
| `GET /api/track/{token}` | public (501 until `order_stage` lands) |

Owner passes every role check. Full schema at http://localhost:8000/docs.
