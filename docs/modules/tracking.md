# Tracking module

Owner: Ashil. Code: `backend/app/modules/tracking/`, `frontend/src/features/tracking/`, screens
`/orders/[id]` and the public `/track/[token]`. Requirements R14, R15.

## What it does

- **Answers "where is my order?"** without anyone walking the floor. The answer is a buyer
  stage: order received → waiting for yarn → in production (stage name and %) → being checked →
  ready to ship → partly shipped → shipped, or cancelled.
- **Shows metres by bucket:** produced, in QC (in process, awaiting QC or rework), passed and on
  the shelf, rejected, shipped.
- **Answers "when?"** It shows the deadline and the projected finish from
  `analytics.delivery_estimate`. Until that function lands it shows "Estimate pending", but a
  deadline that has already passed is still flagged `late`.
- **`/orders/[id]`:** the stage card, timeline, rolls, dispatches and invoices. The owner also
  sees the cost and margin panel (finance). The buyer link box has **Copy link**, **WhatsApp**
  (opens `wa.me` with the buyer's phone and a ready message) and **Email** (opens the mail app
  with the buyer's email, subject and message). The buyer's contact, phone and email come from
  the buyer master and are only on the staff view, never on the public page.
- **`/track/[token]`:** a public, read-only page. It shows the same card and a reduced timeline,
  and refreshes every minute. The buyer does not see rejected metres. Produced counts good
  fabric only, so the gap between the numbers does not reveal the rejects either.
  A **Deliveries** section lists every truck that left: challan number, date and time, rolls,
  metres, vehicle number and driver. Draft and loading trucks are not shown.

## Data flow

```
work_orders (production) + production_logs ─┐
rolls (quality) ───────────────────────────┼─> derive_stage(...)  (pure)  -> card
dispatches + dispatch_rolls (dispatch) ─────┘
analytics.delivery_estimate (stub -> "estimate pending")
```

Nothing is stored. Every request recomputes the stage from the rows.

## Invariants and how each is enforced

| Invariant | Enforced by |
|---|---|
| The stage is derived, never typed | There is no stage column. `derive_stage()` is a pure function of order status, work orders and roll metres. |
| The buyer never sees money or internal IDs | The public route uses `response_model=TrackOut`, which has no rate, cost, buyer or ID fields. FastAPI drops anything else. Test: `test_public_page_shows_stage_and_never_money`. |
| The buyer never sees rejects | `TrackOut.metres` is `BuyerMetres`, which has no `rejected` field. `public_view` reports produced minus rejected. Only `OrderView` (staff) carries `rejected`. Test: `test_rejected_metres_only_for_staff`. |
| The token is unguessable | `secrets.token_urlsafe(24)`: 192 random bits. |
| The token is revocable | `POST /api/track/orders/{id}/rotate-token` (accounts; owner passes) replaces it. The old link returns 404 at once. The change is audited. |
| Only the office sees order internals | `/api/track/orders/{id}` requires accounts or dispatch (owner passes). |

## DSA

**The order stage is a pure function of events.** The rules are checked in order, and the first
one that matches wins:

1. Order cancelled → **cancelled**. Draft → **order received**.
2. Shipped metres ≥ ordered, or order closed → **shipped**. Any shipped metres → **partly shipped**.
3. Passed metres ≥ ordered → **ready to ship**.
4. All route work orders done: rolls still in QC → **being checked**; otherwise any passed metres
   → **ready to ship**.
5. Any work order queued, running, paused or done → **in production**, at the first stage that
   is not done, with % = produced / planned.
6. Otherwise → **waiting for yarn** (all work orders are `waiting`).

Because it's a pure function, it is tested with a table of cases plus the real seed script
(`test_stage_for_every_seeded_order`).

## Five likely evaluator questions

1. **Why not store the status?**
   A typed status drifts from reality. Deriving it from rolls and work orders means it is right
   the moment QC passes a roll or a truck leaves.
2. **Is the public link safe?**
   192-bit random token, read-only, no money or internal IDs, and revocable in one click. There
   is no other way into that endpoint.
3. **What if production progress is not implemented yet?**
   `production.order_progress` is still a stub, so tracking sums `production_logs` per work
   order itself. When Muaz ships the function, it is used automatically.
4. **How does the page stay live?**
   `/orders/[id]` listens to SSE topics `orders`, `dispatch`, `quality` and `machines`, and
   refetches when something changes. The public page polls every 60 s because it has no login
   for SSE.
5. **What does "partly shipped" mean if the rest is still on the loom?**
   Shipping has started; the metres card still shows how much is in production and in QC.
