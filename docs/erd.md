# ER diagram (schema v1)

Source of truth: `backend/app/modules/*/models.py` and `backend/alembic/versions/0001_schema_v1.py`.
Every table also has `id` (identity PK) and `created_at` (timestamptz). Status columns are
VARCHAR with a CHECK constraint. Money is BIGINT paise. Quantities are NUMERIC(12,3).

## Masters, stock, orders

```mermaid
erDiagram
    suppliers ||--o{ expected_deliveries : "will bring"
    suppliers ||--o{ receipts : delivers
    suppliers ||--o{ yarn_batches : "lot from"
    yarn_items ||--o{ expected_deliveries : of
    yarn_items ||--o{ yarn_batches : "identified as"
    receipts ||--o{ yarn_batches : contains
    expected_deliveries |o--o{ receipts : fulfils
    yarn_batches ||--o{ stock_moves : moves
    yarn_batches ||--o{ reservations : "reserved from"
    locations ||--o{ stock_moves : "from / to"
    orders ||--o{ reservations : holds
    buyers ||--o{ orders : places
    fabric_types ||--o{ orders : "made as"
    fabric_types ||--o{ fabric_type_stages : route
    fabric_types ||--o{ fabric_recipe : "yarn mix"

    suppliers {
        string code UK
        string name
        string gstin UK
        bool active
    }
    buyers {
        string code UK
        string name
        string gstin UK
        bool active
    }
    yarn_items {
        string fibre
        string count
        string colour
        numeric reorder_level_kg
        bool active
    }
    fabric_types {
        string code UK
        numeric width_cm
        numeric gsm
        numeric process_loss_pct
    }
    fabric_type_stages {
        int fabric_type_id FK
        int seq
        string stage
    }
    fabric_recipe {
        int fabric_type_id FK
        string fibre
        string count
        numeric share_pct
    }
    locations {
        string code UK
        string kind
    }
    expected_deliveries {
        int supplier_id FK
        int yarn_item_id FK
        numeric expected_kg
        string status
    }
    receipts {
        string code UK
        int supplier_id FK
        bigint bill_amount_paise
        string status
    }
    yarn_batches {
        string code UK
        int receipt_id FK
        string supplier_lot
        numeric received_kg
        bigint unit_cost_paise_per_kg
        string status
    }
    stock_moves {
        string item_kind
        int yarn_batch_id FK
        int roll_id FK
        numeric qty
        string unit
        int from_location_id FK
        int to_location_id FK
        string reason
        string idempotency_key UK
    }
    reservations {
        int yarn_batch_id FK
        int order_id FK
        numeric kg
        string status
    }
    orders {
        string code UK
        int buyer_id FK
        int fabric_type_id FK
        string colour
        numeric qty_m
        bigint rate_paise_per_m
        date deadline
        string status
        string tracking_token UK
    }
```

## Production, quality, dispatch, finance, workforce

```mermaid
erDiagram
    orders ||--o{ work_orders : "one per stage"
    machines ||--o{ work_orders : runs
    machines ||--o{ machine_events : "status history"
    work_orders ||--o{ production_logs : output
    shifts ||--o{ production_logs : in
    work_orders ||--o{ rolls : produces
    machines ||--o{ rolls : "woven on (loom)"
    shifts ||--o{ rolls : "woven in"
    workers |o--o{ rolls : weaver
    rolls ||--o{ roll_batches : "made from"
    yarn_batches ||--o{ roll_batches : "used in"
    rolls ||--o{ qc_checks : inspected
    users ||--o{ qc_checks : inspector
    rolls ||--o{ roll_events : history
    rolls |o--o| work_orders : "rework target"
    orders ||--o{ dispatches : shipped
    dispatches ||--o{ dispatch_rolls : carries
    rolls ||--o| dispatch_rolls : "at most once"
    dispatches ||--o| invoices : billed
    invoices ||--o{ invoice_lines : lines
    rolls ||--o| invoice_lines : "billed once"
    invoices ||--o{ payments : paid
    wage_runs ||--o{ wage_lines : lines
    workers ||--o{ wage_lines : earns
    workers ||--o{ crew_assignments : "on machine"
    machines ||--o{ crew_assignments : staffed
    workers ||--o{ attendance : marked

    work_orders {
        string code UK
        int order_id FK
        string stage
        int seq
        int machine_id FK
        numeric planned_qty
        string status
        int roll_id FK
    }
    machines {
        string code UK
        string type
        bigint hourly_cost_paise
        numeric rated_output_per_hour
        bool active
    }
    machine_events {
        int machine_id FK
        timestamptz at
        string status
        string reason
        string source
    }
    production_logs {
        int work_order_id FK
        int machine_id FK
        int shift_id FK
        numeric qty
        string unit
    }
    rolls {
        string code UK
        int order_id FK
        int work_order_id FK
        int loom_machine_id FK
        numeric length_m
        string status
        string shade_band
        string dye_lot
    }
    roll_batches {
        int roll_id FK
        int yarn_batch_id FK
        numeric kg
    }
    qc_checks {
        int roll_id FK
        int attempt_no
        string decision
        jsonb defects
        string shade_band
    }
    dispatches {
        string code UK
        int order_id FK
        string vehicle_no
        string status
        string delivery_token UK
        string delivery_otp
        datetime delivered_at
        string received_by
        string driver_email
    }
    dispatch_rolls {
        int dispatch_id FK
        int roll_id UK
    }
    invoices {
        string code UK
        int dispatch_id UK
        bigint subtotal_paise
        bigint tax_paise
        bigint total_paise
        string status
    }
    invoice_lines {
        int invoice_id FK
        int roll_id UK
        numeric metres
        bigint amount_paise
    }
    payments {
        int invoice_id FK
        bigint amount_paise
        string mode
    }
    wage_runs {
        date period_start
        date period_end
        string status
    }
    wage_lines {
        int wage_run_id FK
        int worker_id FK
        numeric days
        bigint amount_paise
    }
    workers {
        string code UK
        string wage_type
        bigint daily_rate_paise
        bigint piece_rate_paise_per_m
    }
    shifts {
        string code UK
        time start_time
        time end_time
    }
    crew_assignments {
        date date
        int shift_id FK
        int worker_id FK
        int machine_id FK
        timestamptz from_at
        timestamptz to_at
    }
    attendance {
        date date
        int shift_id FK
        int worker_id FK
        string status
        string source
    }
```

## System tables

| Table | Purpose |
|---|---|
| `users` | Login. `email` unique, bcrypt `password_hash`, `role`, `active`. |
| `audit_log` | Who did what to which record. Written in the same transaction as the change. |
| `code_sequences` | Next number per code prefix (`YB`, `RC`, `SO`, `WO`, `R`, `DN`, `INV`). |
| `idempotency_keys` | Stored response per key, so a repeated scan does not double-post. |
| `insights` | Computed findings (analytics). `facts` JSONB holds the numbers. |
| `expenses` | Power, maintenance, transport, rent, other. For month-end profit. |

## Constraints worth knowing

- `dispatch_rolls.roll_id` UNIQUE: a roll goes on one dispatch, ever (R18).
- `invoices.dispatch_id` UNIQUE and `invoice_lines.roll_id` UNIQUE: one invoice per dispatch, a roll is billed once.
- Partial UNIQUE `work_orders(machine_id) WHERE status = 'running'`: one running job per machine.
- Partial UNIQUE `work_orders(order_id, seq) WHERE roll_id IS NULL`: one work order per stage per order.
- `stock_moves.item_matches_kind`: yarn moves in kg with a batch, fabric moves in metres with a roll.
- `stock_moves.moves_somewhere`: from and to locations differ.
- `qc_checks.pass_has_shade`: a passed roll must have a shade band.
- `machine_events.downtime_has_reason`: breakdown and maintenance need a reason.
- `workers.rate_matches_wage_type`: daily workers need a daily rate, piece workers a piece rate.
- `invoices.total_adds_up`: total = subtotal + tax.
