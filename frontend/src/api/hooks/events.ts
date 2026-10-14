import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useApiClient } from "../../app/auth";
import { backoffMs, followEvents, type StreamEvent, type StreamState } from "../events";
import { openJobEvents, type JobStatus } from "../jobs";
import type { Problem } from "../problem";
import { jobKey, jobResultsKey } from "./jobs";

// SPEC-10 §4.2: after each batch of stored events the stream sends the task counts as `progress`, which is not stored
// and has no id of its own; the job's end event has the kind of the status it ended in.
const PROGRESS = "progress";
const ENDS: ReadonlySet<string> = new Set<JobStatus>(["completed", "failed", "cancelled"]);

export interface JobEvents {
  /** The stored events received, in order. */
  events: StreamEvent[];
  state: StreamState;
  /** Why the stream was refused; null unless `state` is `failed`. */
  problem: Problem | null;
}

/** Follows `GET /v1/jobs/{id}/events` while mounted. A `progress` event reads the job's summary again; the end event
 * reads its summary and results again. */
export function useJobEvents(id: string, delayMs: (attempt: number) => number = backoffMs): JobEvents {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [problem, setProblem] = useState<Problem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const onEvent = (event: StreamEvent) => {
      if (signal.aborted) return;
      if (event.kind === PROGRESS) {
        void queryClient.invalidateQueries({ queryKey: jobKey(id) });
        return;
      }
      setEvents((previous) => [...previous, event]);
      if (ENDS.has(event.kind)) {
        void queryClient.invalidateQueries({ queryKey: jobKey(id) });
        void queryClient.invalidateQueries({ queryKey: jobResultsKey(id) });
      }
    };
    void followEvents({
      open: (lastEventId, abort) => openJobEvents(client, id, lastEventId, abort),
      isEnd: (event) => ENDS.has(event.kind),
      onEvent,
      onState: (next) => {
        if (!signal.aborted) setState(next);
      },
      onProblem: (next) => {
        if (!signal.aborted) setProblem(next);
      },
      signal,
      delayMs,
    });
    return () => {
      controller.abort();
    };
  }, [client, queryClient, id, delayMs]);

  return { events, state, problem };
}
