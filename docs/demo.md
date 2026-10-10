# Judge demo: yarn to profit with the guided tour

One order, followed from a truck of yarn to a paid invoice, in the order of the problem statement's
six scenes. An on-screen guide signs you in as each person, opens their page, rings the thing to
press, and moves on only when the database shows the step happened. About 15 minutes, of which
~5 are the floor weaving and dyeing the order live.

## Before the judges arrive (5 min)

1. `docker compose up -d --wait db`
2. API: `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. Web: `cd frontend && npm run build && npx next start -p 3000 -H 0.0.0.0`
   (low on memory? stop the live feed while `next build` runs)
4. Live machine feed: `cd backend && PYTHONPATH=. uv run python ../scripts/simulate.py --live --api http://127.0.0.1:8000/api --interval 3`
5. Open **http://localhost:3000** (not the LAN IP: the camera only works on localhost or HTTPS).
6. Use **one window**. The tour remembers where it is in this browser; a private window starts
   its own.
7. On the login page press **Take the guided tour** (also in the sidebar once signed in).

## Demo logins

Password for every account: **`demo1234`**. The tour signs in for you; to do it by hand, tap the
role on the login page.

| Role | Email | Lands on |
|---|---|---|
| Owner | `owner@everest.local` | `/owner` |
| Store | `store@everest.local` | `/store` |
| Floor supervisor | `supervisor@everest.local` | `/floor` |
| QC inspector | `qc@everest.local` | `/qc` |
| Dispatch | `dispatch@everest.local` | `/dispatch` |
| Accounts & sales | `accounts@everest.local` | `/orders` |

## The run

The guide panel sits bottom right. Each step shows a live line (green tick when done). **Next**
signs in as the next person when the role changes. **Skip** is there for exceptions; **Back**
reopens an earlier step.

| # | Scene | Who | What you do | What the guide waits for | Problem statement |
|---|---|---|---|---|---|
| 1 | Opening | Owner | Read the briefing, delivery risk | (look) | dashboard |
| 2 | 1 · Yarn at the gate | Store | `/store/receive`: tap a sample label, **Add lot**, **Confirm receipt** | a receipt confirmed after the tour started | R1, R2 |
| 3 | 1 | Store | `/store/batches`: open each lot, **Approve into store** | no lot of that receipt left in inspection | R1, R3 |
| 4 | 1 | Accounts | `/orders/new`: Gowda Uniforms · **Piece-dyed Poplin** · Navy · **110 m** · rate 185 · deadline next month · **Save and confirm** | a new confirmed order (its code is remembered) | R4, R5 |
| 5 | 1 → 2 | Store | `/store` → **Needs yarn** → **Issue** → **Issue to floor** | the order's weaving job is no longer waiting | hand-off |
| 6 | 2 · Floor | Supervisor | `/floor`: the loom that took the job by itself is ringed | that job running | R6–R8 |
| 7 | 2 | Supervisor | Break another running loom with a reason, then **Running** | (look) | R9 |
| 8 | 2 | Supervisor | `/floor/crew`: assign a worker (attendance is written) | (look) | R9, R20 |
| 9 | 2 → 3 | Supervisor | watch: rolls cut every ~60 m, tail roll at plan, then dyeing starts by itself | a roll of the order reaches QC | R7, R10 |
| 10 | 3 · QC | QC | `/qc`: each roll of the order → defects → **Pass**, shade A | floor done, no roll waiting or in rework, one passed | R11, R12 |
| 11 | 3 | QC | the roll's trace: yarn lots, supplier, loom, shift, checks | (look) | R10, R13, D3 |
| 12 | 4 · Buyer asks | Accounts | order page: derived stage; copy the buyer link, open it in a new tab | (look) | R14, R15 |
| 13 | 5 · Dispatch | Dispatch | the draft truck made at the first pass: load rolls, vehicle **KA-01-AB-1234**, **Confirm dispatch**; try loading a roll twice | a confirmed truck for the order | R16–R19, D1 |
| 14 | 5 | Accounts | `/orders`: the order closed itself (shipped within 2 %) | order closed | auto-close |
| 15 | 6 · Month-end | Accounts | `/finance/payments`: record the payment on the invoice | invoice part paid or paid | R19, R24 |
| 16 | 6 | Accounts | `/finance/month`: cost per order (rule on screen), profit; Wages | (look) | R20–R23 |
| 17 | Close | Owner | back on `/owner` | (look) | — |

### What happens by itself (say it while it happens)

- Issuing yarn puts the first job on the least busy working loom, and it starts. Nobody queues it.
- At plan the loom cuts the tail roll and the job finishes. Dyeing is then queued on a free dye range
  and dyes the whole lot; dyed rolls join the QC queue.
- A rework decision sends the roll straight back to a machine, ahead of the queue.
- The first passed roll makes a draft truck. Confirming it makes the invoice from exactly those
  rolls, and closes the order once ≥ 98 % has shipped. Its leftover yarn is reserved for the next
  order that is short.
- Every one of those writes is in the audit log, by the service that made it.

### Side trips if a judge asks

- **Defect analysis** (R13): `/qc` lower half, defects by loom and by order; `/insights` ties colour
  mismatches to Sri Lakshmi Yarns lots.
- **Proof of delivery** (D6): on the truck page, the driver link and the buyer's one-time code.
- **Double dispatch** (R18): a roll can never be on two trucks; it is a UNIQUE constraint in the
  database, not a hidden button.

## If something goes wrong

| Problem | Fix |
|---|---|
| Step 6 says the job is queued behind another | Every loom was busy. On `/floor/work-orders`, move it to a free loom. |
| Floor tiles stop changing | The live feed timed out. Restart step 4 of the setup. |
| The guide is on the wrong step | **Back** or **Skip**; to start over, close it (×) and press **Take the guided tour**. |
| Step 14 says the order is still open | Rejects left it short of 98 %: press **Close** on `/orders` and give the reason. |
| Camera says it needs HTTPS | You are on the LAN IP. Use `http://localhost:3000`. |
| Pictures don't move | Click **Motion · on** on the login page, or the play button in the sidebar. |
| Need a fresh month of data | `make db-reset migrate simulate` (about 15 min). The tour needs no fixed codes. |
