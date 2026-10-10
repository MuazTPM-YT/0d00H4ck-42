# Assumptions

Things the problem statement does not say, and what we chose. Change one only with the team.

- **Mill size.** One site, about 10 machines, 24 workers, 3 shifts. One server on the factory LAN.
- **Roles.** Owner, store, supervisor, QC, dispatch, accounts, sales. Owner can do everything.
- **Route.** Every fabric is woven (rolls are born at weaving). Spinning and dyeing are optional
  stages per fabric type.
- **Dyed fabric.** A fabric with a dyeing stage is woven from `Raw White` yarn. The order colour
  applies at dyeing.
- **Yarn requirement.** Fabric kg = metres × width_m × GSM / 1000. Yarn kg = fabric kg / (1 − loss%),
  split by recipe share.
- **Units.** Yarn in kg. Fabric in metres. Spinning work orders plan in kg, weaving and dyeing in m.
- **Usable stock.** Only approved batches in store locations count. Inspection, quarantine and
  pending-identification stock never counts.
- **Shifts.** A night shift may cross midnight, so end time can be before start time.
- **Attendance.** Filled from crew assignments (who ran which machine). Manual entry only for
  corrections.
- **Wages.** Daily-wage workers paid per day present (half day = 0.5). Piece-rate workers paid per
  metre woven.
- **Tax.** GST 5% on cotton fabric (HSN 5208) in demo invoices. Invoice due 30 days after dispatch.
- **Cost per order.** Yarn at actual GRN unit cost consumed (FIFO), labour by machine-hours per
  shift, machine cost at its hourly rate, plus rework and reject cost. The rule is shown in the UI.
- **Time.** Stored in UTC, shown in IST.
- **Money.** Indian rupees, stored in paise.
- **Buyer tracking link.** Anyone with the token can read that one order's stage. No costs or internal IDs shown.
- **Offline.** No feature needs the internet.
