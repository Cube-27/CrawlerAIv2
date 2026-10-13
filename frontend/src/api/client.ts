import createClient from "openapi-fetch";
import type { paths } from "./schema";

export interface ApiClientOptions {
  baseUrl: string;
  /** Held in memory by the caller and sent as a bearer header (ARCHITECTURE §18); never persisted here. */
  apiKey?: string;
}

/** A typed client for the backend API. `paths` is generated from `openapi.json` by `pnpm gen:api`. */
export function createApiClient({ baseUrl, apiKey }: ApiClientOptions) {
  return createClient<paths>({
    baseUrl,
    headers: apiKey === undefined ? {} : { Authorization: `Bearer ${apiKey}` },
  });
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** A client of the API on this page's origin: `pnpm dev` proxies `/v1` to the backend (vite.config.ts). Created per
 * call, so it uses the `fetch` in place at that time. */
export function sameOriginClient(): ApiClient {
  return createApiClient({ baseUrl: window.location.origin });
}
