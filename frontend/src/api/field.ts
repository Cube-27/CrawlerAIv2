/** The field shape the API returns for every extracted field (SPEC-07 §4.4, ARCHITECTURE §13.1), narrowed to what
 * the shared field components read until the generated `schema.d.ts` carries the record schema. */

/** A field's resolution status (SPEC-05 §4.2 `FieldOutcome.status`). */
export type FieldStatus = "published" | "missing" | "conflict" | "abstained";

export interface FieldResult {
  status: FieldStatus;
  /** Why a field did not publish (`disagree`, `below_tau`, …); null when it published. */
  reason: string | null;
  /** The normalized value, shaped by the field's type (SPEC-04 §4.4); the server sends it only when published. */
  value: unknown;
}

/** The §5.1 field types whose values are a single scalar or a fixed-shape object (SPEC-04 §4.4). */
export type ScalarFieldType =
  | "text"
  | "long_text"
  | "money"
  | "enum"
  | "url"
  | "image_url"
  | "identifier"
  | "date"
  | "datetime"
  | "location"
  | "range";

/** A field's type as the schema declares it (SPEC-04 §4.1): what the UI needs to display its value. */
export type FieldTypeSpec =
  | { type: ScalarFieldType }
  | { type: "list"; item: FieldTypeSpec }
  | { type: "object"; fields: Readonly<Record<string, FieldTypeSpec>> };
