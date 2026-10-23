import type { MapRequest } from "../../../api/jobs";
import { optionalNumber } from "../pageRequest";
import { count, flag, text, texts, type StoredRequest } from "../run/storedRequest";

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

/** The form that shows the stored `request` of a map job. */
export function mapForm(request: StoredRequest): MapFormState {
  return {
    url: text(request, "url"),
    options: {
      include: texts(request, "include"),
      exclude: texts(request, "exclude"),
      useSitemaps: flag(request, "use_sitemaps", DEFAULT_MAP_OPTIONS.useSitemaps),
      useLinks: flag(request, "use_links", DEFAULT_MAP_OPTIONS.useLinks),
      limit: count(request, "limit"),
    },
  };
}
