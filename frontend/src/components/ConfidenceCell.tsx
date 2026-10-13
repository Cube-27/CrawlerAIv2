import { StatusLabel } from "./StatusLabel";

/** A field's confidence as a number with two decimals, never a bar: a bar implies a calibration the value may not have
 * (DESIGN.md, Showing extraction results). An uncalibrated value carries a visible badge. */
export function ConfidenceCell({
  confidence,
  calibrated,
}: Readonly<{ confidence: number | null; calibrated: boolean }>) {
  return (
    <span className="inline-flex items-center gap-2">
      {confidence === null ? "—" : confidence.toFixed(2)}
      {calibrated ? null : <StatusLabel text="uncalibrated" tone="warning" />}
    </span>
  );
}
