/** The parts of an RFC 9457 problem the UI shows. SPEC-07 §4.3 defines the full body; this narrows it until the
 * generated `schema.d.ts` carries the problem schema. */
export interface ProblemSummary {
  title: string;
  detail: string | null;
}

// RFC 9457 §3: problem bodies are `application/problem+json`; RFC 9110 §8.3.1 allows parameters after `;`.
function isProblemJson(response: Response): boolean {
  const mediaType = response.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase();
  return mediaType === "application/problem+json";
}

/** The problem in `response`, or null when the body is not a problem with a title. Consumes the body. */
export async function readProblem(response: Response): Promise<ProblemSummary | null> {
  if (!isProblemJson(response)) return null;
  const body: unknown = await response.json().catch(() => null);
  if (typeof body !== "object" || body === null) return null;
  const { title, detail } = body as Record<string, unknown>;
  if (typeof title !== "string") return null;
  return { title, detail: typeof detail === "string" ? detail : null };
}
