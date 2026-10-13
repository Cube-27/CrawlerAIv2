import type { SchemaDef } from "../api/schemas";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per `schema_def.status` (ARCHITECTURE §6): a retired version stays readable but takes no new work.
const SCHEMA_STATUS_TONES: Record<SchemaDef["status"], StatusTone> = {
  active: "success",
  retired: "neutral",
};

/** A schema version's status as its text and icon. */
export function SchemaStatusLabel({ status }: Readonly<{ status: SchemaDef["status"] }>) {
  return <StatusLabel text={status} tone={SCHEMA_STATUS_TONES[status]} />;
}
