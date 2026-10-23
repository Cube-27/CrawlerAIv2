import type { MapRequest, StoredJobRequest } from "../../../api/jobs";
import { optionalNumber } from "../pageRequest";

/** Map's options panel: each is a `MapRequest` member. An empty limit (NaN) is left out. */
export interface MapOptions {
  include: readonly string[];
  exclude: readonly string[];
  useSitemaps: boolean;
  useLinks: boolean;
  limit: number;
}

// MapRequest's own defaults: both sources are read.
export const DEFAULT_MAP_OPTIONS: MapOptions = {
  include: [],
  exclude: [],
  useSitemaps: true,
  useLinks: true,
  limit: Number.NaN,
};

export interface MapFormState {
  url: string;
  options: MapOptions;
}

export const INITIAL_MAP: MapFormState = { url: "", options: DEFAULT_MAP_OPTIONS };

export function buildMap(form: MapFormState): MapRequest {
  const { options } = form;
  return {
    url: form.url,
    include: [...options.include],
    exclude: [...options.exclude],
    use_sitemaps: options.useSitemaps,
    use_links: options.useLinks,
    ...optionalNumber("limit", options.limit),
  };
}

/** The form that shows the stored request of a map job, null for a job of another kind. */
export function mapForm(stored: StoredJobRequest): MapFormState | null {
  if (stored.kind !== "map") return null;
  const { request } = stored;
  return {
    url: request.url,
    options: {
      include: request.include,
      exclude: request.exclude,
      useSitemaps: request.use_sitemaps,
      useLinks: request.use_links,
      limit: request.limit,
    },
  };
}
