import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { Problem } from "../problem";
import type { ApiResult } from "../result";

/** A failed API call, as TanStack Query carries it: the problem to show. */
export class ApiProblem extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.title);
    this.name = "ApiProblem";
    this.problem = problem;
  }
}

/** The value of `result`, or its problem thrown as an `ApiProblem` (a query or mutation function's contract). */
export async function unwrap<T>(result: Promise<ApiResult<T>>): Promise<T> {
  const answer = await result;
  if (answer.kind === "failed") throw new ApiProblem(answer.problem);
  return answer.value;
}

/** The problem a failed query or mutation carries; null while it has not failed. */
export function problemOf(error: Error | null): Problem | null {
  if (error === null) return null;
  if (error instanceof ApiProblem) return error.problem;
  return { title: "Something went wrong.", detail: error.message, errors: [], retryAfter: null };
}

function newQueryClient(): QueryClient {
  return new QueryClient({
    // A failed call shows its problem at once; the viewer retries. A 401 also shows the setup notice (`useApiClient`).
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Server state for the screens (SPEC-12 §4.1). */
export function ApiQueryProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [client] = useState(newQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
