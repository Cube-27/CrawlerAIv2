import type { FieldTypes, FieldTypeSpec } from "../../../api/field";
import type { JsonValuesItem } from "../../../api/jobs";
import { isJsonObject, type JsonObject } from "../../../api/json";
import type { ScrapeRecord, ScrapeResponse } from "../../../api/scrape";

type CleanRecord = JsonValuesItem["records"][number];

/** Code-unit order of two strings, the order Python's `sorted` gives the server. */
function codeUnitOrder(a: string, b: string): number {
  if (a < b) return -1;
  return a > b ? 1 : 0;
}

/** The key of a money field's currency, as the server's clean record names it (`config_ir/exporters/records.py`):
 * `currency` beside `price`, else `<name>_currency`, the first that names no field; null when both do, and the money
 * value is then written whole. */
function currencyKey(name: string, fields: FieldTypes): string | null {
  const candidates = name === "price" ? ["currency", `${name}_currency`] : [`${name}_currency`];
  return candidates.find((key) => !(key in fields)) ?? null;
}

function cleanValue(value: unknown, spec: FieldTypeSpec | undefined): unknown {
  if (spec?.type === "list" && Array.isArray(value)) {
    return value.map((item: unknown) => cleanValue(item, spec.item));
  }
  if (spec?.type === "object" && isJsonObject(value)) return cleanObject(spec.fields, value);
  return value;
}

/** `data` as a clean record (SPEC-14 §4.4), as the server writes one for `json_values`: its published fields in name
 * order, a null one left out, and a money value flat as its amount beside its currency. Names are ASCII
 * (`NAME_PATTERN`), so code-unit order is name order (D-0816). */
function cleanObject(fields: FieldTypes, data: JsonObject): CleanRecord {
  const clean: Record<string, unknown> = {};
  for (const name of Object.keys(data).sort(codeUnitOrder)) {
    const value = data[name];
    if (value === null || value === undefined) continue;
    const spec = fields[name];
    const currency = spec?.type === "money" ? currencyKey(name, fields) : null;
    if (currency !== null && isJsonObject(value)) {
      clean[name] = value.amount;
      clean[currency] = value.currency;
    } else {
      clean[name] = cleanValue(value, spec);
    }
  }
  return clean;
}

/** A record's clean form: each field's published value (SPEC-07 §4.4: `value` is null unless published). */
function cleanRecord(record: ScrapeRecord, fieldTypes: FieldTypes): CleanRecord {
  const data = Object.fromEntries(
    Object.entries(record.fields).map(([name, field]) => [name, field.value ?? null]),
  );
  return cleanObject(fieldTypes, data);
}

/** A page's JSON as the playground shows it: its one record as an object, or its records as an array (none, or a
 * listing's), with no URL or outcome around them. With `metadata` (Metadata in JSON) they sit under `data`. */
export function pageJson(records: readonly CleanRecord[], metadata?: unknown): unknown {
  const data = records.length === 1 ? records[0] : records;
  return metadata === undefined || metadata === null ? data : { data, metadata };
}

/** One scrape's page JSON (`pageJson`), its records cleaned as the server cleans a job's (`json_values`). */
export function scrapeJson(
  response: ScrapeResponse,
  fieldTypes: FieldTypes,
  withMetadata: boolean,
): unknown {
  const records = (response.records ?? []).map((record) => cleanRecord(record, fieldTypes));
  return pageJson(records, withMetadata ? response.metadata : undefined);
}
