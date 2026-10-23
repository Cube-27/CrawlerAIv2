/** The Recipes screens' routes (app/router.tsx). */
export function recipesPath(host: string): string {
  return `/sites/${encodeURIComponent(host)}/recipes`;
}

export function newRecipePath(host: string): string {
  return `${recipesPath(host)}/new`;
}

export function recipePath(id: string): string {
  return `/recipes/${id}`;
}
