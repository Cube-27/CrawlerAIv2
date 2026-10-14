/** The site and config screens' routes (app/router.tsx). */
export function sitePath(host: string): string {
  return `/sites/${encodeURIComponent(host)}`;
}

export function configPath(id: string): string {
  return `/configs/${id}`;
}
