/** The parts of an RFC 9457 problem the UI shows. SPEC-07 §4.3 defines the full body; this narrows it until the
 * generated `schema.d.ts` carries the problem schema. */
export interface ProblemSummary {
  title: string;
  detail: string | null;
}

/** One entry of a problem's `errors` (SPEC-07 §4.3): the request member and why it was refused. */
export interface FieldProblem {
  field: string;
  reason: string;
}

export interface Problem extends ProblemSummary {
  errors: FieldProblem[];
}

// RFC 9457 §3: problem bodies are `application/problem+json`; RFC 9110 §8.3.1 allows parameters after `;`.
export function isProblemJson(response: Response): boolean {
  const mediaType = response.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase();
  return mediaType === "application/problem+json";
}

function isFieldProblem(entry: unknown): entry is FieldProblem {
  if (typeof entry !== "object" || entry === null) return false;
  return (
    "field" in entry &&
    typeof entry.field === "string" &&
    "reason" in entry &&
    typeof entry.reason === "string"
  );
}

/** The problem in a parsed body, or null when it is not a problem with a title. Malformed `errors` entries are
 * skipped. */
export function parseProblem(body: unknown): Problem | null {
  if (typeof body !== "object" || body === null) return null;
  if (!("title" in body) || typeof body.title !== "string") return null;
  const detail = "detail" in body && typeof body.detail === "string" ? body.detail : null;
  const errors = "errors" in body && Array.isArray(body.errors) ? body.errors : [];
  return {
    title: body.title,
    detail,
    errors: errors.filter(isFieldProblem).map(({ field, reason }) => ({ field, reason })),
  };
}

/** The problem in `response`, or null when the body is not a problem with a title. Consumes the body. */
export async function readProblem(response: Response): Promise<Problem | null> {
  if (!isProblemJson(response)) return null;
  return parseProblem(await response.json().catch(() => null));
}
