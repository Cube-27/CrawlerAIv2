import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useApiClient } from "../../app/auth";
import { backoffMs, followEvents, IDLE_MS, type StreamEvent, type StreamState } from "../events";
import { openJobEvents, type JobStatus } from "../jobs";
import type { Problem } from "../problem";
import { jobKey, jobResultsKey } from "./jobs";

// after each batch of stored events the stream sends the task counts as `progress`, which is not stored
// and has no id of its own; the job's end event has the kind of the status it ended in.
const PROGRESS = "progress";
const ENDS: ReadonlySet<string> = new Set<JobStatus>(["completed", "failed", "cancelled"]);
// The events that end a task with a result: the results shown are read again after them, at most once
// per REFRESH_MS, so a fast run does not read the page once per task.
const TASK_ENDS: ReadonlySet<string> = new Set(["task_extracted", "task_failed"]);
export const REFRESH_MS = 1000;

/** `run` at most once per `ms`: at once when the last run is `ms` old, otherwise once when it will be. `cancel` drops
 * a run still waiting. */
function throttled(run: () => void, ms: number) {
  let last = Number.NEGATIVE_INFINITY;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const fire = () => {
    timer = undefined;
    last = Date.now();
    run();
  };
  return {
    call: () => {
      if (timer !== undefined) return;
      const wait = last + ms - Date.now();
      if (wait <= 0) fire();
      else timer = setTimeout(fire, wait);
    },
    cancel: () => {
      clearTimeout(timer);
    },
  };
}

export interface JobEvents {
  /** The stored events received, in order. */
  events: StreamEvent[];
  state: StreamState;
  /** Why the stream was refused; null unless `state` is `failed`. */
  problem: Problem | null;
}

interface EventSinks {
  refresh: ReturnType<typeof throttled>;
  readAgain: (queryKey: readonly unknown[]) => void;
  id: string;
  append: (event: StreamEvent) => void;
}

/** One stored or progress event: a task's end reads the results again (throttled); progress and the end read the
 * summary again; the end reads the results at once, cancelling a refresh still waiting that would read them again. */
function handleEvent(event: StreamEvent, { refresh, readAgain, id, append }: EventSinks) {
  if (TASK_ENDS.has(event.kind)) refresh.call();
  const ended = ENDS.has(event.kind);
  if (event.kind === PROGRESS || ended) readAgain(jobKey(id));
  if (event.kind === PROGRESS) return;
  append(event);
  if (ended) {
    refresh.cancel();
    readAgain(jobResultsKey(id));
  }
}

/** Follows `GET /v1/jobs/{id}/events` while mounted. A `progress` event reads the job's summary again; a task's end
 * reads its results again, at most once per `REFRESH_MS`; the end event reads its summary and results again. A reconnect reads the summary again too: the stream resumes after the last
 * event, but `progress` is not stored, so the counts come only from the summary. */
export function useJobEvents(
  id: string,
  delayMs: (attempt: number) => number = backoffMs,
): JobEvents {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [problem, setProblem] = useState<Problem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    const refresh = throttled(() => {
      if (!signal.aborted) void queryClient.invalidateQueries({ queryKey: jobResultsKey(id) });
    }, REFRESH_MS);
    const readAgain = (queryKey: readonly unknown[]) =>
      void queryClient.invalidateQueries({ queryKey });
    const onEvent = (event: StreamEvent) => {
      if (!signal.aborted) {
        handleEvent(event, {
          refresh,
          readAgain,
          id,
          append: (e) => {
            setEvents((previous) => [...previous, e]);
          },
        });
      }
    };
    let previous: StreamState = "connecting";
    void followEvents({
      open: (lastEventId, abort) => openJobEvents(client, id, lastEventId, abort),
      isEnd: (event) => ENDS.has(event.kind),
      onEvent,
      onState: (next) => {
        if (signal.aborted) return;
        if (previous === "reconnecting" && next === "live") {
          void queryClient.invalidateQueries({ queryKey: jobKey(id) }, { cancelRefetch: false });
        }
        previous = next;
        setState(next);
      },
      onProblem: (next) => {
        if (!signal.aborted) setProblem(next);
      },
      signal,
      delayMs,
      idleMs: IDLE_MS,
    });
    return () => {
      controller.abort();
      refresh.cancel();
    };
  }, [client, queryClient, id, delayMs]);

  return { events, state, problem };
}
