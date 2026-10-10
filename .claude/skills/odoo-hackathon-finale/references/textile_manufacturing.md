# PS: Textile Manufacturing System (Everest Textile Mills)

Read this when the team has chosen the Textile PS. It turns the six scenes into a requirements checklist, a data model and demo moments.

The PS replaces: notebook stock, walking the floor for machine and order status, paper QC (Quality Check) slips, phone calls to buyers, and a paper register for attendance and wages. The closing line sets the bar: the owner must know the real cost of a roll and whether the mill made money.

## Requirements checklist (copy into docs/requirements.md)

Scene 1, yarn arrives at the gate
- [Core] R1. Record a yarn receipt: supplier, yarn type, colour, quantity (kg), unit cost, optionally linked order. This is a GRN (Goods Receipt Note).
- [Core] R2. Live raw material stock per yarn type and colour.
- [Core] R3. Low-stock warning against a per-material reorder level, visible on the dashboard.
- [Core] R4. On a new order, show whether available yarn covers it, and the shortfall if not.
- [Expected] R5. Reserve yarn for an order so two orders cannot claim the same stock.

Scene 2, the production floor
- [Core] R6. Machines with type (spinning, weaving, dyeing) and status (running, idle, breakdown, maintenance).
- [Core] R7. Assign an order stage to a machine; show which order is on which machine and its progress.
- [Core] R8. Live floor board: every machine's current job, status, and output today. Updates without reload.
- [Expected] R9. Log breakdowns with reason and time down; shifts and workers assigned to machines.

Scene 3, quality check
- [Core] R10. Each produced roll gets a unique ID linked to order, machine, shift.
- [Core] R11. QC record per roll: pass, rework, reject, with defect type (hole, colour mismatch, uneven weave, other).
- [Core] R12. Queue of rolls waiting for QC; pass/fail summary.
- [Expected] R13. Defect analysis by machine and by order, so a defect can be traced to its cause.

Scene 4, a buyer asks about their order
- [Core] R14. Order status derived from real data: Confirmed → In Production (stage) → Quality Check → Ready to Ship → Dispatched.
- [Core] R15. Answer "where is my order" instantly: an order detail page, and a read-only buyer tracking link (tokenised URL, no login).

Scene 5, dispatch
- [Core] R16. Finished goods stock: rolls on the shelf (QC passed, not dispatched).
- [Core] R17. Dispatch: pick specific rolls for a buyer's order, vehicle details, quantity check against order.
- [Core] R18. A roll can never be dispatched twice (enforced by a DB constraint, not only UI).
- [Core] R19. Invoice generated from the dispatched rolls, matching quantities and rates.

Scene 6, month-end books
- [Core] R20. Worker attendance per shift, and wages computed from it.
- [Core] R21. Cost per order: yarn consumed + labour + machine cost (state the allocation rule in the UI).
- [Core] R22. Production per machine for a period.
- [Core] R23. Monthly profit view: buyer payments and invoices vs raw material bills and wages.
- [Expected] R24. Record buyer payments against invoices; outstanding receivables.
- [Stretch] R25. Export reports (CSV or PDF).

Cross-cutting
- [Core] Roles: Admin/Owner, Store, Supervisor (floor), QC Inspector, Accounts. Server enforces per endpoint.
- [Expected] Activity log on orders and rolls.

## Data model sketch

- `suppliers`, `buyers`
- `materials` (yarn type, colour, unit, reorder_level)
- `stock_moves` (material_id, qty signed, type: receipt, reserve, release, consume; ref to GRN or order). Stock = SUM of moves. Never a mutable counter: this one decision gives you history, low-stock checks, availability and audit for free.
- `fabric_types` with yarn requirement per metre (a simple BOM, Bill of Materials)
- `orders` (buyer, fabric_type, colour, qty_m, deadline, rate, status)
- `machines` (code, type, status)
- `work_orders` (order_id, stage, machine_id, planned_qty, produced_qty, started_at, finished_at, status)
- `shifts`, `workers`, `attendance` (worker, shift, date, present, hours), `wage_rates`
- `rolls` (code, order_id, machine_id, shift_id, length_m, qc_status)
- `quality_checks` (roll_id, inspector, result, defect_type, notes)
- `dispatches` (buyer, order, vehicle, date), `dispatch_rolls` (dispatch_id, roll_id UNIQUE)
- `invoices`, `payments`, `purchase_bills`
- `machine_events` (breakdown and status history, for idle time and per-machine output)

## Demo moments that win

1. New order → system shows yarn shortfall → receive yarn → order becomes startable.
2. Two windows: supervisor marks a machine as breakdown, floor board updates live.
3. Roll fails QC for colour mismatch → trace view shows machine and shift → defect chart by machine.
4. Buyer tracking link opened on a phone shows the exact stage.
5. Try dispatching an already-dispatched roll: server rejects it.
6. Month-end page: cost per order and profit for the month, from data created in the demo.

## Traps

- Status fields typed by hand drift from reality. Derive order status from work orders, rolls and dispatches.
- Cost per order needs a stated rule (for example labour cost allocated by machine-hours per shift). Pick one, show it, be ready to defend it.
- Units: kg for yarn, metres for fabric. Store the unit, never mix silently.
- Do not build a full accounting system. Income and expense lines with a monthly summary are enough.

## Scene 1 detailed design (team flow, with fixes)

Flow: expected delivery (lightweight purchase order) → receive and verify → internal batch ID + QR → quarantine → approve → usable stock → availability check on order → reserve → issue to production.

- Yarn spec is first-class: type/blend, count (e.g. Ne 30/1), colour (allow "raw white"), supplier lot. Mismatch on any field puts the batch in Quarantine; only a QC/Store manager role can release it, with a reason.
- Locations are part of the stock ledger: `stock_moves` carry from/to location. Receipt moves into an Inspection location; approval moves it to a usable location. Available = usable stock minus reservations. Quarantined or unidentified stock never counts.
- Quantity variance: store expected and received. Flag outside a configurable tolerance per material (cotton yarn weight varies with moisture, so tiny gaps are not automatically shortages). Never auto-adjust.
- Idempotent receiving: unique (supplier_id, supplier_lot, receipt_id); rescanning opens the existing batch. Stock changes only when the receipt is confirmed, in one transaction.
- Supplier labels vary by supplier; treat the scanned value as a string to match against the expected lot. No OCR. Missing label → "Pending identification" batch.
- Scanning input is a text field that accepts USB/Bluetooth scanner input (keyboard wedge); camera scan is optional. Phone camera access needs HTTPS or localhost, so a phone hitting the laptop's LAN IP over plain HTTP cannot use the camera. Demo camera scanning on the laptop at localhost, or set up local HTTPS.
- Yarn requirement: order quantity in metres; fabric type stores width, GSM, process loss %, and yarn components with share %. Fabric kg = metres × width_m × GSM / 1000; yarn kg = fabric kg / (1 − loss %), split by component share.
- Reservation prefers a single supplier lot per order component (mixing yarn lots causes barre / shade variation). If lots must be mixed, warn and record it on the order. Lock rows during reservation so two orders cannot reserve the same kilos.
- Issue to production: issue against reservation; over-issue needs a reason; support return-to-store for unused yarn. Each issue move keeps batch → work order link for traceability.
- Core: expected delivery, receive/verify with flags, batch + QR, quarantine/approve, availability check, reserve, issue. Expected: bin locations with scan-to-confirm, missing-label flow. Stretch: phone camera scanning.
