# Dispatch module

Owner: Ashil. Code: `backend/app/modules/dispatch/`, `frontend/src/features/dispatch/`,
screens `/stock/finished`, `/dispatch`, `/dispatch/[id]`. Requirements R16 to R19, D1.

## What it does

- **Finished stock.** Rolls that passed QC and are still on the shelf, grouped by order. Each roll
  shows location, shade band, days on shelf and the dispatch it sits on (if any).
- **Corner check.** Lists rolls that have been on the shelf longer than N days (default 7), rolls
  whose order is no longer open, and leftovers from orders that are already fully shipped.
- **Create dispatch.** For one confirmed order. The screen suggests which rolls to load.
- **Loading by scan.** Each roll is scanned (or typed) onto the truck. The server checks it and
  returns a running count, the metres loaded and the metres still to load.
- **Confirm.** In one transaction:
  - every roll goes `passed` → `dispatched`;
  - a stock move FG → DISP is written for each roll;
  - the invoice is created from exactly the loaded rolls.

  The screen then shows a printable delivery challan.
- **Gone-out register.** Every dispatch, filterable by status, vehicle and date.

## Data flow

```
QC pass -> roll status passed, stock move WIP -> FG-01
   |
/stock/finished  (dispatch.shelf + corner_check)
   |
POST /dispatch/dispatches            draft, code DN-xxxxxx
POST /dispatch/dispatches/{id}/scan  dispatch_rolls row; draft -> loading on first roll
PUT  /dispatch/dispatches/{id}/vehicle
POST /dispatch/dispatches/{id}/confirm
   -> roll.status dispatched, roll.location DISP
   -> stock_moves FG-01 -> DISP (reason dispatch, ref dispatch)
   -> finance.issue_invoice: invoice + one line per roll
   -> audit rows, commit, publish dispatch / stock / orders
```

## Invariants and how each is enforced

| Invariant | Enforced by |
|---|---|
| A roll is dispatched at most once | DB: `dispatch_rolls.roll_id` UNIQUE. Service: the scan locks the dispatch row and then the roll row (`FOR UPDATE`), and checks whether the roll is already on any dispatch. Test: `test_two_scanners_cannot_load_one_roll_twice` runs two real sessions at the same moment. |
| Only passed rolls ship | Scan rejects anything not `passed` (409 `not_passed`). Confirm runs `check_transition(ROLL_TRANSITIONS, status, dispatched)`. |
| Right buyer | Scan rejects a roll from another order (409 `wrong_order`). The dispatch's buyer is copied from the order, never typed. |
| Right quantity | Once the loaded rolls cover the remaining metres, any further scan is rejected (409 `order_covered`). The screen shows ordered, shipped earlier, on this truck and still to load. |
| One shade band per truck | A roll of another band is rejected (409 `shade_mismatch`) unless a supervisor has posted an override with a reason. The override is an audit row. Confirm checks the bands again. |
| Scans are idempotent | `idempotency_key` goes through `run_once`, so a repeat returns the first answer. Scanning the same roll onto the same truck again does nothing. |
| Stock never goes negative | Before writing FG → DISP, confirm checks from the ledger that the roll's metres really are at its location (409 `stock_mismatch`). |
| Invoice equals what was loaded | Invoice lines are built inside the confirm transaction from the locked list of loaded rolls. Test: `test_confirm_makes_invoice_from_exactly_the_loaded_rolls`. |
| Confirmed dispatch is final | Transition map: `draft → loading → confirmed` (and `loading → draft` when the last roll is taken off). Nothing leaves `confirmed`. |

## DSA

**Roll picking is a subset-sum problem** (`dispatch.service.pick_rolls`, a pure function). The
goal is to reach the remaining metres with the least overshoot, using one shade band.

1. Group free rolls by shade band.
2. In each band, go through the rolls from largest to smallest and take each one that still fits
   under the need.
3. If the band is still short, add the **smallest** roll that was skipped. Every skipped roll
   overshot when it was skipped, so any of them closes the gap; the smallest overshoots least.
4. Among bands that cover the need, pick the one with the least overshoot, then the fewest rolls.
   If no band covers it, pick the band that gets closest and report how short it is.

Cost is O(n log n) for the sort. On the shelf, rolls are roughly the same length (55 to 70 m), so
greedy is close to optimal.

**When to use dynamic programming instead:** when rolls vary a lot in length, or the buyer pays
for exact metres and overshoot is expensive. Exact subset-sum DP over decimetres is
O(n × need_dm). For 40 rolls and 3,000 m that is 40 × 30,000 = 1.2M cells, which is still fast.
It was left out because greedy is easy to explain and the clerk can adjust the suggestion anyway.

## Five likely evaluator questions

1. **What stops two clerks loading the same roll on two trucks?**
   Both scans lock the roll row, so the second waits. When it continues, it sees the first
   dispatch's row and gets 409 `already_dispatched`. If the code were ever bypassed, the UNIQUE
   constraint on `dispatch_rolls.roll_id` rejects the insert. A test proves it with two
   concurrent sessions.
2. **Why is the invoice made at confirm and not by accounts?**
   The truck is the fact. Building the lines from the loaded rolls inside the same transaction
   means an invoice cannot disagree with what left the gate, and nobody types metres twice.
3. **Why greedy and not optimal?**
   See DSA above. It is fast and close to optimal for similar roll lengths. The clerk can still
   pick different rolls, and the server validates whatever is scanned.
4. **Where is the shade override stored?**
   As an audit row (`action = shade_override`, with the reason and user). A proper column is
   requested in `schema-requests.md`.
5. **Why does dispatch write stock moves and roll status, which belong to other modules?**
   Agreed with the team (decision 21). Confirm must be one transaction. The write uses the
   quality module's transition map and the ledger's own rules, and is listed in
   `contracts.md`.
