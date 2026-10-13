import { useCallback, useEffect, useState } from "react";
import type { ApiResult } from "./result";

export type Query<T> = { kind: "loading" } | ApiResult<T>;

const LOADING = { kind: "loading" } as const;

/** Runs `load` when it changes (memoize it with `useCallback`) and again on `reload`; an answer to an earlier `load`
 * is dropped. A reload keeps the last answer on screen until the new one arrives. */
export function useApiQuery<T>(load: () => Promise<ApiResult<T>>): [Query<T>, () => void] {
  const [answer, setAnswer] = useState<{ load: typeof load; result: Query<T> }>({
    load,
    result: LOADING,
  });
  const [run, setRun] = useState(0);

  useEffect(() => {
    let current = true;
    void load().then((result) => {
      if (current) setAnswer({ load, result });
    });
    return () => {
      current = false;
    };
  }, [load, run]);

  const reload = useCallback(() => {
    setRun((count) => count + 1);
  }, []);
  // An answer to another `load` (an earlier route's id) is not this one's.
  return [answer.load === load ? answer.result : LOADING, reload];
}
