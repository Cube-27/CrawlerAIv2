export type JsonObject = Readonly<Record<string, unknown>>;

/** A JSON object (RFC 8259 §4): not null, not an array. */
export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The JSON object in `text`, or null when it is not one. */
export function parseJsonObject(text: string): JsonObject | null {
  try {
    const value: unknown = JSON.parse(text);
    return isJsonObject(value) ? value : null;
  } catch {
    return null;
  }
}
