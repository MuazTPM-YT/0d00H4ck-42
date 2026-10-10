# Judge demo: yarn to profit in about 10 minutes

One story, six scenes, the same order of the problem statement. Every step names the login, the
page and what to click. Codes below are from the dev database built by the simulator (seed 42);
if one was used up in a rehearsal, take the next row on the same screen.

## Before the judges arrive (5 min)

1. `docker compose up -d --wait db`
2. API: `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. Web: `cd frontend && npm run build && npx next start -p 3000 -H 0.0.0.0`
4. Live machine feed: `cd backend && PYTHONPATH=. uv run python ../scripts/simulate.py --live --api http://127.0.0.1:8000/api --interval 3`
5. Open **http://localhost:3000** (not the LAN IP: the camera only works on localhost or HTTPS).
6. Two windows side by side: a normal one and a private one (two logins at once).
7. On the login page, click **Motion · on** (bottom left of the picture) so the prints move.

## Demo logins

Password for every account: **`demo1234`**. On the login page you can just tap the role.

| Role | Email | Name | Lands on |
|---|---|---|---|
| Owner | `owner@everest.local` | Rajesh Agarwal | `/owner` |
| Store | `store@everest.local` | Suresh Naik | `/store` |
| Floor supervisor | `supervisor@everest.local` | Manjunath Gowda | `/floor` |
| QC inspector | `qc@everest.local` | Priya Raman | `/qc` |
| Dispatch | `dispatch@everest.local` | Imran Shaikh | `/dispatch` |
| Accounts & sales | `accounts@everest.local` | Kavitha Rao | `/orders` |
| Accounts & sales (2nd login) | `sales@everest.local` | Arjun Mehta | `/orders` |

## Demo data to use

| What | Value | Where you use it |
|---|---|---|
| Buyer for the new order | Gowda Uniforms | Scene 1, `/orders/new` |
| Fabric for the new order | Cotton Shirting 40s (SHIRT40), Navy, 6,000 m | Scene 1, shows a yarn shortfall |
| Supplier with planted colour problems | Sri Lakshmi Yarns (SLY) | Scene 3, insights |
| Loom that keeps breaking / slows down | LM-03, LM-05 | Scenes 2 and 3 |
| Loom to break live | LM-04 (running) | Scene 2 |
| Worker to search and assign | Ramesh Kumar (W-001) | Scene 2, crew |
| Roll waiting for QC | R-000240 (order SO-000013, loom LM-05, 64 m) | Scene 3, `/qc` |
| Order to track and dispatch | SO-000009, Patel Fashion House, 1,300 m Raw White, 20 rolls on the shelf | Scenes 4 and 5 |
| Buyer tracking link for SO-000009 | `/track/U8-uIkHHXTM5B9cGFHHnUJWiMc9-7XXz` | Scene 4 |
| Roll already dispatched (for the double-dispatch test) | R-000361 (order SO-000011) | Scene 5 |
| Vehicle number | KA-01-AB-1234 | Scene 5 |
| Month to close | September 2026 | Scene 6 |

## The run

### 0. Open (owner, 30 s)
1. `/login`: tap **Owner**. The print switches to the mill, Everest behind it. Sign in.
2. `/owner`: read the briefing line out loud ("12 things need you today…"), then the four figures:
   invoiced, cash received, month result, fabric woven. Point at **Delivery risk**: on track /
   at risk / late, from real progress, not a typed status.

### 1. Yarn arrives at the gate (accounts, then store, 2 min) — R1–R5
1. Private window: log in as **Accounts & sales** → `/orders/new`.
2. Buyer **Gowda Uniforms**, fabric **Cotton Shirting 40s**, colour **Navy**, **6,000 m**, any
   deadline next month. The yarn panel shows needed / free / **short** kg live as you type.
   Save. Say: stock is a ledger of moves, never a typed number, and reservation row-locks the
   lots so two orders can never claim the same kilos.
3. Normal window: log in as **Store** → `/store` shows low-stock warnings against reorder levels.
4. `/store/receive` → **Expected delivery** → supplier **Kaveri Spinning Mills**, Ne 40/1 Navy.
5. Open **Sample labels** (`/store/receive/labels`) on a phone or print one. Back on
   `/store/receive`, press **Camera** next to the scan box and hold the QR up (or type the label
   and press Enter). A spec mismatch goes to **quarantine**; weight gaps over 2 % are flagged,
   never adjusted. Confirm the receipt.
6. `/store/stock`: Ne 40/1 Navy went up. The new order's shortfall shrinks.

### 2. The production floor (supervisor, 2 min) — R6–R9, R20
1. Normal window: log in as **Floor supervisor** → `/floor`. Every machine: job, progress, made
   today, crew. Running looms move (the shuttle); stopped ones stand still.
2. Private window: log in as **Owner** → `/owner` (or a second `/floor`).
3. Normal window: click **LM-04** → **Breakdown** → reason **Belt slip** → save.
   The tile turns red at once **in both windows, no reload** (server-sent events). Its job pauses.
4. Click LM-04 again → **Running**. The job can resume; downtime is logged with the reason.
5. `/floor/work-orders`: which order is on which machine, queue order, move a job.
6. `/floor/crew`: type **Ramesh** in the search (or press `/`), press Enter, assign him to
   **LM-01**. Attendance for the shift is written from the crew sheet.

### 3. Quality check (QC, 2 min) — R10–R13
1. Log in as **QC inspector** → `/qc`. Top: waiting, passed, rework, rejected, pass rate.
2. Click **R-000240** (SO-000013, LM-05). The sheet shows order, loom, shift, length.
3. Choose **Reject**, defect **Colour mismatch** ×1, save. It leaves the queue; the counts move.
4. Scroll to **Defects by loom** and **Defects by order**: LM-05 and LM-03 stand out.
5. Owner window → `/insights`: the finding that ties colour mismatches to **Sri Lakshmi Yarns**
   lots, traced through roll → yarn batch → supplier.

### 4. A buyer asks "where is my order?" (accounts, 1 min) — R14–R15
1. **Accounts & sales** → `/orders` → **SO-000009**. Stage is derived: confirmed → in production
   (stage) → QC → ready → dispatched, with metres at each step.
2. Open the buyer link on a phone: `http://<laptop-ip>:3000/track/U8-uIkHHXTM5B9cGFHHnUJWiMc9-7XXz`.
   No login, read only, rejected rolls hidden from the buyer.

### 5. Dispatch (dispatch, 2 min) — R16–R19
1. Log in as **Dispatch** → `/stock/finished`: SO-000009 has 20 rolls passed and on the shelf.
2. `/dispatch` → **New dispatch** → order **SO-000009**, vehicle **KA-01-AB-1234**.
3. On the dispatch page, scan the proposed rolls (type each code, or **Camera**). The quantity
   check counts metres against the order.
4. Now scan **R-000361**. The server refuses: it is already on another dispatch. Say: it is a
   UNIQUE constraint in the database, not just a button that hides.
5. **Confirm**. The invoice is made from exactly those rolls → `/finance/invoices`.

### 6. Month-end books (accounts, 1.5 min) — R20–R24
1. **Accounts & sales** → `/finance/wages`: wages computed from the attendance captured on the floor.
2. `/finance/payments`: record a payment against the new invoice; receivables update.
3. `/orders/9` (SO-000009): **cost per order** = yarn consumed + labour + machine time, with the
   allocation rule written on the screen.
4. `/finance/month` → **September 2026**: invoiced and cash basis, yarn bills, wages, expenses,
   the result, and production per machine.
5. Close on `/owner`: "the owner knows the real cost of a roll and whether the mill made money."

## If something goes wrong

| Problem | Fix |
|---|---|
| Floor tiles stop changing | The live feed timed out. Restart step 4 of the setup. |
| A code above is already used | Take the next row on the same list (QC queue, shelf, orders). |
| Camera says it needs HTTPS | You are on the LAN IP. Use `http://localhost:3000`. |
| Pictures don't move | Click **Motion · on** on the login page, or the play button in the sidebar. |
| Need a fresh month of data | `make db-reset migrate simulate` (about 15 min; codes may shift, re-read them from the screens). |
