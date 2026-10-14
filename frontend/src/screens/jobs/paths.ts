/** The job screens' routes (app/router.tsx). */
export function jobPath(id: string): string {
  return `/jobs/${encodeURIComponent(id)}`;
}
