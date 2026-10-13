import { useQuery } from "@tanstack/react-query";
import { sameOriginClient } from "../client";
import { getHealth } from "../health";
import { unwrap } from "./query";

/** Whether the backend serves the labeling API (`/healthz.eval_ui`, SPEC-12 §4.3). False while unknown or when the
 * call fails: the nav entry then stays hidden, and `/labeling` still says when the API is off. The flag is fixed for
 * the backend's lifetime, so it is read once per cache. */
export function useEvalUi(): boolean {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: () => unwrap(getHealth(sameOriginClient())),
    staleTime: Infinity,
  });
  return data?.eval_ui === true;
}
