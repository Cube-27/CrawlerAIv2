/** The schema screens' routes (app/router.tsx). */
export function schemaPath(id: string): string {
  return `/schemas/${id}`;
}

export function editSchemaPath(id: string): string {
  return `/schemas/${id}/edit`;
}

/** A new schema prefilled from the schema `id`: how a prompt draft is adopted. */
export function adoptSchemaPath(id: string): string {
  return `/schemas/new?from=${encodeURIComponent(id)}`;
}
