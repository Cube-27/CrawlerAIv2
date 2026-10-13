import { isJsonObject } from "../../api/json";
import type { RecordField } from "../../api/scrape";

/** One field of a stored record beside the same field of its replay; a side is null when that record lacks the field. */
export interface FieldChange {
  name: string;
  stored: RecordField | null;
  replayed: RecordField | null;
  changed: boolean;
}

type Fields = Readonly<Record<string, RecordField>>;

// JSON values compare by content: objects by their members in any order (RFC 8259 §4 leaves member order
// insignificant), arrays in order.
function sameJson(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length && left.every((item, index) => sameJson(item, right[index]))
    );
  }
  if (isJsonObject(left) && isJsonObject(right)) {
    const keys = Object.keys(left);
    return (
      keys.length === Object.keys(right).length &&
      keys.every((key) => key in right && sameJson(left[key], right[key]))
    );
  }
  return left === right;
}

function sameField(stored: RecordField | null, replayed: RecordField | null): boolean {
  if (stored === null || replayed === null) return false;
  return stored.status === replayed.status && sameJson(stored.value, replayed.value);
}

/** Every field either record has, by name, and whether the replay changed its status or its value. Confidence,
 * evidence and locator are shown but not compared: the same value can be published from another source. */
export function diffFields(stored: Fields, replayed: Fields): FieldChange[] {
  const names = [...new Set([...Object.keys(stored), ...Object.keys(replayed)])].sort();
  return names.map((name) => {
    const before = stored[name] ?? null;
    const after = replayed[name] ?? null;
    return { name, stored: before, replayed: after, changed: !sameField(before, after) };
  });
}
