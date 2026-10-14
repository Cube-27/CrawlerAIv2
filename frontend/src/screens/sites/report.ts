/** What the validation and release reports share in how they are shown. */

/** `count` of `total` pages. */
export function ofPages(count: number, total: number): string {
  return `${String(count)}/${String(total)}`;
}

/** A listing's row fields with its next-page step as one more row, when it has one. A field name is
 * `[a-z][a-z0-9_]*` (SPEC-04), so "next page" never hides one. */
export function withNextPage<T>(
  fields: Readonly<Record<string, T>>,
  next: T | null | undefined,
): Readonly<Record<string, T>> {
  return next == null ? fields : { ...fields, "next page": next };
}
