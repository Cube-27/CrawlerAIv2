import createClient from "openapi-fetch";
import type { paths } from "./schema";

export interface ApiClientOptions {
  baseUrl: string;
}

/** A typed client for the backend API. `paths` is generated from `openapi.json` by `pnpm gen:api`. It sends no
 * credentials: the server that serves the UI attaches the API key (frontend spec). */
export function createApiClient({ baseUrl }: ApiClientOptions) {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** A client of the API on this page's origin: `pnpm dev` proxies `/v1` to the backend (vite.config.ts). Created per
 * call, so it uses the `fetch` in place at that time. */
export function sameOriginClient(): ApiClient {
  return createApiClient({ baseUrl: window.location.origin });
}
