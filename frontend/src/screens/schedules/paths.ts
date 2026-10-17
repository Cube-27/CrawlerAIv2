/** The schedule screens' routes (app/router.tsx). */
export function schedulePath(id: string): string {
  return `/schedules/${encodeURIComponent(id)}`;
}
