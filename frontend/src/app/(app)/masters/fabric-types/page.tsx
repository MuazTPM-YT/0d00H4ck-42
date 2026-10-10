"use client";

import type { Column } from "@/components/layout/DataTable";
import { StatusBadge } from "@/components/layout/StatusBadge";
import type { Row } from "@/features/masters/config";
import { type FabricRow, FabricTypeForm } from "@/features/masters/FabricTypeForm";
import { MasterList } from "@/features/masters/MasterList";
import { humanize } from "@/lib/format";

const columns: Column<Row>[] = [
  { key: "code", header: "Code", className: "font-medium", cell: (r) => r.code as string },
  { key: "name", header: "Name", cell: (r) => r.name as string },
  { key: "spec", header: "Width × GSM", cell: (r) => `${Number(r.width_cm)} cm × ${Number(r.gsm)}` },
  { key: "loss", header: "Loss", className: "text-right", cell: (r) => `${Number(r.process_loss_pct)}%` },
  { key: "route", header: "Route", cell: (r) => (r as FabricRow).stages.map((s) => humanize(s.stage)).join(", then ") },
  { key: "recipe", header: "Yarn", cell: (r) => (r as FabricRow).recipe.map((x) => `${x.fibre} ${x.count} ${Number(x.share_pct)}%`).join(" + ") },
  { key: "active", header: "Status", cell: (r) => <StatusBadge status={r.active ? "active" : "off"} /> },
];

export default function Page() {
  return (
    <MasterList
      path="fabric-types"
      title="Fabric types"
      singular="fabric type"
      description="Width, GSM, loss, route and yarn recipe for each fabric."
      columns={columns}
      hasActive
      renderForm={(row, done) => <FabricTypeForm row={row as FabricRow | null} onDone={done} />}
    />
  );
}
