import type { Endpoint, FieldMatch } from "../../api/captures";

/** One endpoint group as text, stable while samples are added: method, origin, path shape, query names and body
 * shape, as the server groups calls by them. */
export function endpointKey(endpoint: Endpoint): string {
  return JSON.stringify([
    endpoint.method,
    endpoint.origin,
    endpoint.has_path,
    endpoint.segments,
    endpoint.query,
    endpoint.body_shape,
  ]);
}

/** The URL shape people read: `GET https://example.test/{3 segments}?page&size`. */
export function endpointText(endpoint: Endpoint): string {
  const path = endpoint.has_path ? `/{${segmentsText(endpoint.segments)}}` : "/";
  const query = endpoint.query.length === 0 ? "" : `?${endpoint.query.join("&")}`;
  return `${endpoint.method ?? "GET"} ${endpoint.origin}${path}${query}`;
}

function segmentsText(segments: number): string {
  return segments === 1 ? "1 segment" : `${String(segments)} segments`;
}

/** Whether any call of the group went to the page's own site (the server's `same_site`, RFC 6265bis §5.2). */
export function isOwnSite(endpoint: Endpoint): boolean {
  return endpoint.calls.some((call) => call.same_site === true);
}

/** The groups with the page's own site first; otherwise in the server's order (first called first). */
export function ownSiteFirst(endpoints: readonly Endpoint[]): Endpoint[] {
  return [...endpoints.filter(isOwnSite), ...endpoints.filter((endpoint) => !isOwnSite(endpoint))];
}

/** Where a group carries one field, a line per path: "price at $.data.price on 3 of 3", then "in the text on 2 of 3"
 * for an HTML answer that holds the published value. A path read by type only, not by a published value, says so. */
export function matchLines(match: FieldMatch, samples: number): string[] {
  const of = (count: number) => `on ${String(count)} of ${String(samples)}`;
  const { field, in_text: inText } = match;
  const kind = match.published ? "" : " (by type)";
  const lines = match.paths.map(
    ({ path, samples: count }) => `${field} at ${path} ${of(count)}${kind}`,
  );
  return inText > 0 ? [...lines, `${field} in the text ${of(inText)}`] : lines;
}

/** A byte count as people read it: "512 B", "3.4 kB" (SI, ISO/IEC 80000-13). */
export function sizeText(bytes: number): string {
  if (bytes < 1000) return `${String(bytes)} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(1)} kB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}
