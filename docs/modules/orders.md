# Orders module (order entry)

Owner: Ammaar. Code: `backend/app/modules/orders/`, `frontend/src/features/orders/`, screens
`/orders` and `/orders/new`. The order detail page `/orders/[id]` belongs to tracking (Ashil) and
can embed `OrderYarnPanel`. Covers R4: "is there enough yarn to start this order?"

## What it does

1. **Sales enters the order:** buyer, fabric, colour, metres, rate per metre, deadline. While they
   type, `POST /orders/requirement-preview` shows needed / free / short per recipe line.
2. **Save** creates a `draft` order `SO-000123`.
3. **Confirm** runs in one transaction:
   - `draft → confirmed`
   - `production.create_work_orders`: one work order per route stage
   - `inventory.reserve`: free yarn locked to the order

   If any step fails, all three roll back.
4. **To-buy list.** For each confirmed order line: short, free stock that can cover it now, yarn
   already on order, and what is left to buy. "Order from supplier" opens a prefilled expected
   delivery tagged to the order. When that yarn is approved, it is reserved for the order.
5. **Cancel** releases the order's reservations (with a reason).

## Requirement formula

`fabric kg = metres × width_m × GSM / 1000`. `yarn kg = fabric kg / (1 − loss%)`, split by
recipe share. A fabric with a dyeing stage is woven from `Raw White` yarn, and the order colour
is applied at dyeing. Worked example: 1000 m × 1.5 m × 120 g/m² / 1000 = 180 kg fabric;
/ 0.9 = 200 kg yarn.

## Invariants

| Rule | Where |
|---|---|
| Order status only by map (`draft → confirmed/cancelled`, `confirmed → cancelled/closed`) | `ORDER_TRANSITIONS` + `check_transition`; a second confirm is 409 |
| Confirm is all or nothing | One transaction, one `db.commit()` in `confirm_order`; shared services never commit |
| Valid input | Pydantic: metres > 0 with at most 3 dp, rate > 0, deadline after today and within 2 years, colour not blank. Active buyer and fabric checked in the service. DB CHECKs as the last guard |
| Buyer-facing stage is not stored | `orders.status` is commercial only; the stage comes from tracking |
| Mixed lots recorded | Derived from reservations (more than one batch on a line). An audit row `mixed_lots` is written when it happens |

## Five questions an evaluator is likely to ask

1. **Where does "free" come from?** `inventory.free_stock` = approved kg in store − active
   reservations, computed from the ledger.
2. **Why Raw White for a maroon dyed fabric?** The mill weaves greige (undyed) cloth and dyes it
   later, so the loom needs white yarn. This is in `yarn_components` and tested.
3. **What if there is not enough yarn?** Confirm still reserves what is free. The rest shows on the
   to-buy list, and one click turns it into an expected delivery tagged to the order.
4. **Can sales confirm the same order twice and double the work orders?** No. The second confirm
   is a 409 `illegal_transition`, and `create_work_orders` returns the existing set anyway.
5. **Why compute the to-buy list instead of storing it?** It is derived from orders, reservations,
   issues and deliveries. A stored list would go stale the moment yarn arrives.
