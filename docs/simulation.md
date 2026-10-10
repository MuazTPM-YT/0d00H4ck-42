# Month simulator

`scripts/simulate.py` replays 30 days of mill life into an empty database, so dashboards and the
AI layer have history. Same seed, same month, every time (`backend/tests/test_simulate.py`).

```
make db-reset migrate simulate   # DESTRUCTIVE: wipes the dev DB, then masters + 30 days
make dev                         # in one terminal
make simulate-live               # in another: machine feed every 3 s, the floor board moves
```

Options: `--days 30 --seed 42`, live mode `--interval 3 --api http://localhost:8000/api`.

## How it runs

- Hour by hour, from 06:00 IST thirty days ago to the current hour.
- Every floor action goes through the real services: machine events, queue, start, move, finish,
  output logs, roll cuts, dyeing, rework work orders, crew assignments, attendance. Each call gets
  the simulated time (`at`), so nothing reads the wall clock.
- Steps owned by other modules run through **stand-ins** in one marked block, each with
  `# TODO(swap): <module> <service>`. They write the same rows the real services will: codes,
  `stock_moves`, statuses through the owner's transition map, audit rows. Swap each one for the
  real call when that module merges:

| Stand-in | Swap for |
|---|---|
| `receive_yarn` | inventory receive + approve (Ammaar) |
| `new_order` | orders create + confirm (Ammaar) |
| `reserve_yarn` | `inventory.reserve` |
| `issue_reserved_yarn` | `inventory.issue_to_work_order` |
| `qc_decision` | quality QC decision (Razan); rework already calls `production.create_rework_work_order` |
| `dispatch_ready`, `ship` | dispatch create / load / confirm (Ashil) |
| `invoice_dispatch`, `receive_payment` | finance invoice and payment (Ashil) |

- Not simulated: wage runs, expenses, insights.
- Audit rows get the real `created_at` (the wall clock at run time), not the simulated time.
  Domain tables carry the simulated time.

## What a run produces (seed 42, run on 10 Oct 2026)

44 orders (25 closed), 135 work orders, 1,330 machine events, 4,500 output logs, 1,090 rolls,
1,100 QC checks, 108 dispatches with invoices, 728 attendance rows. The run takes about a minute.

## Planted problems

The AI layer's detectors are validated against these. Look them up by the codes and machines
below. Exact ids and times are printed in the JSON at the end of each run under `planted`.

| # | Problem | How it is planted | How to see it |
|---|---|---|---|
| 1 | Supplier SLY (Sri Lakshmi Yarns) lots cause colour mismatch about 3× as often on the same looms | QC stand-in: colour-mismatch chance 3% normally, 9% when the roll's `roll_batches` include an SLY batch. Receipts rotate KSM, SLY, DCS, so SLY yarn runs on every loom | First QC attempt, rolls with SLY yarn: 7.9% mismatch (547 rolls); others: 3.0% (495 rolls) |
| 2 | LM-03 throughput falls for days, then the loom breaks down | Days 17 to 22: output factor drops 5% a day (95% to 70%), no random breakdowns. Day 23 from 09:00: breakdown "Main shaft bearing seized", 10 hours | LM-03 metres a day: about 390, then 376, 368, 353, 338, 317, 295, 279, then 220 on the breakdown day, back to 388 after repair |
| 3 | One order uses about 8% more yarn than its fabric accounts for | The 5th order (`SO-000005`) gets 8% extra on each yarn issue where the batch has free stock, audited as `over_issue` "Extra for broken ends" | Finished weaving jobs, issued kg vs Σ `roll_batches.kg`: SO-000005 +8.0%, every other order at most +0.4% |
| 4 | Machines idle long at one shift change | At 06:00 IST (shift C to A) running machines go idle 40 to 60 min; at 14:00 and 22:00 only 3 to 8 min | Idle spells starting on the hour: 06:00 average 50 min; 14:00 and 22:00 average 5 min |
| 5 | Output logged while the machine was in breakdown | LM-05 breaks down ("Take-up roller jam", 3 h) on days 8 and 20 when it has a job. After repair its counter uploads 6 m stamped 70 min earlier, inside the breakdown. The API accepts it because the machine is running when the log arrives | 2 `production_logs` on LM-05 whose `at` falls between a `breakdown` event and the next event |

Detector notes:
- Problem 3: compare only weaving jobs that are `done`. A job in progress has yarn issued up front
  and rolls still to come, so its gap is large and normal.
- Problem 5 is the "impossible data" check: an output log time inside a downtime window.
- Rework jobs (`work_orders.roll_id` set) log the reworked roll's length as output on that machine.
  Leave them out when measuring a machine's throughput.

## Live mode

`--live` logs in as `supervisor@everest.local` over HTTP (stdlib `urllib`, Bearer token) and every
few seconds, for each machine on the board:
- running with a weaving or spinning job: posts output (`source=machine`), cuts a roll every ~20 m;
- 2% chance per tick: breakdown with a reason, back to running after 4 to 10 ticks;
- idle with a paused job: reports running again.

Each post goes through the normal API, so the SSE topic `machines` refreshes every open board.
