import { problemOf, type Problem } from "./problem";

/** What one API call came to: its value, or the problem to show. */
export type ApiResult<T> = { kind: "done"; value: T } | { kind: "failed"; problem: Problem };

/** An openapi-fetch answer: `data` on success, the parsed body as `error` otherwise. */
interface Answer<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function failure(
  title: string,
  detail: string | null,
  retryAfter: string | null = null,
): { kind: "failed"; problem: Problem } {
  return { kind: "failed", problem: { title, detail, errors: [], retryAfter } };
}

/** The problem an error answer carries, or a stand-in naming `what` failed and the HTTP status. */
export function failed(response: Response, error: unknown, what: string) {
  const problem = problemOf(response, error);
  return problem === null
    ? failure(
        `${what} failed (HTTP ${String(response.status)}).`,
        null,
        response.headers.get("Retry-After"),
      )
    : { kind: "failed" as const, problem };
}

async function send<T>(
  call: () => Promise<Answer<T>>,
): Promise<Answer<T> | { kind: "failed"; problem: Problem }> {
  try {
    return await call();
  } catch (error_) {
    return failure(
      "The API could not be reached.",
      error_ instanceof Error ? error_.message : null,
    );
  }
}

/** Runs `call` and returns the body it answered with, or why it failed (`what` names the call in that message). A 401
 * also drops the key, through the client's middleware (`useApiClient`). */
export async function apiResult<T>(
  call: () => Promise<Answer<T>>,
  what: string,
): Promise<ApiResult<T>> {
  const answer = await send(call);
  if ("kind" in answer) return answer;
  const { data, error, response } = answer;
  return data === undefined ? failed(response, error, what) : { kind: "done", value: data };
}

/** As `apiResult`, for a call whose success has no body (RFC 9110 §15.3.5, 204 No Content). */
export async function apiDone(
  call: () => Promise<Answer<unknown>>,
  what: string,
): Promise<ApiResult<null>> {
  const answer = await send(call);
  if ("kind" in answer) return answer;
  const { error, response } = answer;
  return response.ok ? { kind: "done", value: null } : failed(response, error, what);
}
