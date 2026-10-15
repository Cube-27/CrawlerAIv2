import type { MapRequest } from "../../../api/jobs";

/** Map's options panel (SPEC-14 §4.2): each is a `MapRequest` member. An empty limit (NaN) is left out. */
export interface MapOptions {
  include: readonly string[];
  exclude: readonly string[];
  useSitemaps: boolean;
  useLinks: boolean;
  limit: number;
}

// MapRequest's own defaults (SPEC-10 §4.4): both sources are read.
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
    ...(Number.isNaN(options.limit) ? {} : { limit: options.limit }),
  };
}
