import { isJsonObject } from "./json";

/** The field shape the API returns for every extracted field (rest-api spec), narrowed to what
 * the shared field components read until the generated `schema.d.ts` carries the record schema. */

/** A field's resolution status (extraction spec `FieldOutcome.status`). `interaction_required` (reason `render_bound`):
 * missing from a page no render ran for, whose source in the site's config is the browser. */
export type FieldStatus =
  | "published"
  | "missing"
  | "conflict"
  | "abstained"
  | "interaction_required";

export interface FieldResult {
  status: FieldStatus;
  /** Why a field did not publish (`disagree`, `below_tau`, …); null when it published. */
  reason: string | null;
  /** The normalized value, shaped by the field's type (schemas spec); the server sends it only when published. */
  value: unknown;
}

/** The §5.1 field types whose values are a single scalar or a fixed-shape object (schemas spec). */
const SCALAR_FIELD_TYPES = [
  "text",
  "long_text",
  "money",
  "enum",
  "url",
  "image_url",
  "identifier",
  "date",
  "datetime",
  "location",
  "range",
  "count",
  "number",
] as const;

export type ScalarFieldType = (typeof SCALAR_FIELD_TYPES)[number];

/** A field's type as the schema declares it (schemas spec): what the UI needs to display its value. */
export type FieldTypeSpec =
  | { type: ScalarFieldType }
  | { type: "list"; item: FieldTypeSpec }
  | { type: "object"; fields: Readonly<Record<string, FieldTypeSpec>> };

function isFieldTypeSpec(value: unknown): value is FieldTypeSpec {
  if (!isJsonObject(value)) return false;
  const { type } = value;
  if (type === "list") return isFieldTypeSpec(value.item);
  if (type === "object")
    return isJsonObject(value.fields) && Object.values(value.fields).every(isFieldTypeSpec);
  const scalars: readonly unknown[] = SCALAR_FIELD_TYPES;
  return scalars.includes(type);
}

/** Each field's type by its name, as a schema declares them. */
export type FieldTypes = Readonly<Record<string, FieldTypeSpec>>;

/** The field types in a schema's `fields` member (schemas spec), in the order of `order`, a field it lacks last; a field whose type is not one of these is left out,
 * and its value is then shown as the server sent it. */
export function parseFieldTypes(fields: unknown, order?: readonly string[]): FieldTypes {
  if (!isJsonObject(fields)) return {};
  const known = Object.entries(fields).filter((entry): entry is [string, FieldTypeSpec] =>
    isFieldTypeSpec(entry[1]),
  );
  // `order` is the schema's `field_order`: the document's order, which a JSON object does not promise to carry.
  const place = (name: string) => {
    const index = order?.indexOf(name) ?? -1;
    return index === -1 ? Number.MAX_SAFE_INTEGER : index;
  };
  return Object.fromEntries([...known].sort(([a], [b]) => place(a) - place(b)));
}
