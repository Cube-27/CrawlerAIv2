import type { RecordField } from "../api/scrape";

/** A published field with every §13.1 attribute set; `overrides` replaces any of them. */
export function recordField(overrides: Partial<RecordField>): RecordField {
  return {
    value: "Blue kettle",
    status: "published",
    reason: null,
    evidence: "structured",
    confidence: 0.97,
    calibrated: true,
    source_kind: "jsonld",
    locator: "jsonld:0:$.name",
    derived_by: null,
    ...overrides,
  };
}
