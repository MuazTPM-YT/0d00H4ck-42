"use client";

import { masterByPath } from "@/features/masters/config";
import { MasterForm } from "@/features/masters/MasterForm";
import { MasterList } from "@/features/masters/MasterList";

const master = masterByPath("workers");

export default function Page() {
  return <MasterList {...master} renderForm={(row, done) => <MasterForm master={master} row={row} onDone={done} />} />;
}
