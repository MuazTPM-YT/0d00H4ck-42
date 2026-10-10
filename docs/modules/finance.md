# Finance module

Owner: Ashil. Code: `backend/app/modules/finance/`, `frontend/src/features/finance/`, screens
`/finance/invoices`, `/finance/payments`, `/finance/wages`, `/finance/month` and the cost panel on
`/orders/[id]`. Requirements R19 to R25 (R22 machine production shown on `/finance/month`), D4.

## What it does

- **Invoices.** Made only by dispatch confirm (`finance.issue_invoice`): one line per roll at the
  order rate. GST is shown separately (5%, HSN 5208). Due 30 days after dispatch. The invoice is
  printable.
- **Payments.** Recorded against an invoice. Status moves `issued → part_paid → paid` as the money
  adds up. The outstanding list puts the oldest due first and shows days overdue.
- **Wage runs.** Draft → final → paid.
  - Daily-rated: days present × day rate (half day = 0.5).
  - Piece-rated weavers: metres woven × rate per metre.
  - A draft can be recomputed after attendance corrections.
- **Order cost** (`finance.order_cost`): yarn + machine + labour, cost per metre and per roll,
  margin, and the allocation rule as text shown on screen.
- **Machine production:** metres or kg per machine per day and per month, plus running, idle,
  breakdown, maintenance and off hours.
- **Month-end:** money in, money out and the result on an invoiced basis and on a cash basis.
  Every number opens the records behind it.
- **Expenses:** power, maintenance, transport, rent and other costs, entered by accounts.

## Data flow

```
dispatch confirm ─> issue_invoice ─> invoices + invoice_lines
payments ─────────> invoice status (transition map)
attendance + production_logs ─> wage_lines (computed, never typed)
stock_moves(issue/return, ref work_order) + yarn_batches.unit_cost ─┐
machine_events spans (running, work_order_id) x machines.hourly ────┼─> order_cost
production_logs (piece) + crew_assignments (daily) ─────────────────┘
invoices, payments, receipts, wage_runs, expenses ─> month view + drilldown
```

## Invariants and how each is enforced

| Invariant | Enforced by |
|---|---|
| Invoice lines come from dispatched rolls | Built only inside dispatch confirm. There is no API to create or edit a line. DB: `invoice_lines.roll_id` UNIQUE, `total = subtotal + tax` CHECK. |
| Invoice status follows payments | `record_payment` locks the invoice, compares the sum paid with the total and moves the status through `INVOICE_TRANSITIONS`. There is no endpoint to set it by hand. |
| No overpayment | Amount > outstanding → 409 on `amount_paise`. A fully paid invoice → 409. |
| Sane payment dates | Not in the future (Pydantic) and not before the invoice date (service). |
| No double wage payment | A run that overlaps an existing period → 409. DB: UNIQUE (period_start, period_end) and one line per worker per run. |
| Wages are not typed | Lines are computed from attendance and logs. Only a draft can be recomputed; `final` locks the run. |
| Money is exact | BIGINT paise everywhere. Rounding is half-up, once per line (`line_amount_paise`). |
| Yarn rejected back to the supplier is not a cost of the month | `_yarn_bills` nets rejected batches off the receipt bill, in the total and the rows |
| Wage runs never overlap, even when two are created at once | transaction lock `WAGE_RUN_LOCK`, then the overlap check |

## Cost allocation rule (also shown on screen)

1. **Yarn:** every kg issued to the order's work orders, priced at the GRN cost of the batch it
   came from, minus kg returned. Consumption moves are not counted again.
2. **Machine:** hours each machine ran the order's work orders (machine event log) × the
   machine's hourly cost.
3. **Labour:**
   - Piece-rated weavers: metres woven for this order × their piece rate.
   - Daily-rated crew: day rate × (hours their machine ran this order during their shift ÷
     shift length).
4. **Rework and rejects:** they used real inputs, so they stay in the cost. The share carried by
   rejected metres is shown separately.
5. **Per metre and per roll:** cost per metre = total ÷ passed metres; cost per roll = total ÷
   passed rolls. Margin = invoiced before GST − total cost.

## DSA

- **FIFO cost layers for yarn.** Each yarn batch is a cost layer (kg at its own GRN price), laid
  down in receipt order. The store issues the oldest layer first (inventory's job). Each issue
  move names its batch, so finance prices every kg at the cost of the exact layer it came from;
  returns reduce that same layer. This gives the same answer as a FIFO queue walk, but stays
  exact even when the store breaks FIFO for a good reason, such as keeping one lot for shade.
  The cost panel lists the layers oldest first.
- **Machine time as spans.** Machine events are sorted per machine. Each event lasts until the
  next one, clipped to the window: O(n log n). The same function feeds order cost and machine
  hours, so the two always agree.
- **Interval overlap for crew labour:** `max(0, min(end1, end2) − max(start1, start2))`.

## Choices

- **Piece wages use metres logged at the loom, not metres of passed rolls.** `assumptions.md`
  says weavers are paid per metre woven, and a weaver should not lose pay because the yarn or the
  dyeing caused a defect. Rejected metres still show up in order cost.
- **Wage runs are dated by period end**, because there is no `paid_at` column yet (schema
  request filed).
- **Yarn bills count when the receipt is confirmed**, because supplier payments are not tracked
  yet. This is stated on the month page.

## Five likely evaluator questions

1. **How do you know the order cost is right?**
   `test_order_cost_hand_calculated` builds a small order by hand and checks every rupee: two
   batches, a return, 10 loom hours, a helper on half a shift, a weaver, passed and rejected
   rolls.
2. **Why two results on the month page?**
   Invoiced basis shows what was earned this month. Cash basis shows what actually came in and
   went out. An owner needs both: profitable on paper but short of cash is a real risk.
3. **Can accounts change an invoice amount?**
   No. No endpoint does that. Lines come from rolls, status comes from payments, and every
   payment is audited.
4. **What stops a wage being paid twice for the same days?**
   Overlapping runs are rejected, `final` locks the lines, and `paid` is a one-way transition.
5. **Why are GST and receipts mixed in the cash result?**
   Cash received includes GST collected; the note on the page says so. Splitting GST payable is
   the next step, once the tax filing flow exists.
