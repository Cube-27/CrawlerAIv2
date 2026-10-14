import type { ConfigStatus, FieldConfigStatus } from "../api/configs";
import { StatusLabel, type StatusTone } from "./StatusLabel";

// One tone per `extraction_config.status` (SPEC-08 §4.8): only the active version serves; a draft did not pass
// validation; a suspended version was replaced by a newer active one.
const CONFIG_STATUS_TONES: Record<ConfigStatus, StatusTone> = {
  active: "success",
  draft: "warning",
  suspended: "neutral",
};

// One tone per field status (SPEC-08 §4.7, §4.9): corroborated by structured values, validated without that, set by an
// operator, or suspended when its yield or validity drifted.
const FIELD_STATUS_TONES: Record<FieldConfigStatus, StatusTone> = {
  corroborated: "success",
  uncorroborated: "warning",
  operator: "accent",
  suspended: "danger",
};

/** A config version's status as its text and icon. */
export function ConfigStatusLabel({ status }: Readonly<{ status: ConfigStatus }>) {
  return <StatusLabel text={status} tone={CONFIG_STATUS_TONES[status]} />;
}

/** A config field's status as its text and icon. */
export function FieldConfigStatusLabel({ status }: Readonly<{ status: FieldConfigStatus }>) {
  return <StatusLabel text={status} tone={FIELD_STATUS_TONES[status]} />;
}
