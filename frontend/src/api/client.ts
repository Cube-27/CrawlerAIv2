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
