import { useMutation, useQuery } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import { captureCalls, captureSample, getCall, getHar, type CaptureRequest } from "../captures";
import { recipeCalls } from "../recipes";
import { unwrap } from "./query";

/** The Recipes screen's builder endpoints as TanStack Query hooks; every key starts with `recipes`. A capture is
 * stored once and never changes, so its calls are read once. */
const RECIPES = ["recipes"] as const;

/** Captures a sample page; the screen keeps the answer, so nothing is read again. */
export function useCaptureSample() {
  const client = useApiClient();
  return useMutation({
    mutationFn: (body: CaptureRequest) => unwrap(captureSample(client, body)),
  });
}

/** The samples' calls by endpoint: one capture's own list, or the list two or more merge into; none without a
 * sample. */
export function useCallList(captureIds: readonly string[]) {
  const client = useApiClient();
  const [only] = captureIds;
  return useQuery({
    queryKey: [...RECIPES, "calls", ...captureIds],
    queryFn: () =>
      unwrap(
        captureIds.length === 1 && only !== undefined
          ? captureCalls(client, only)
          : recipeCalls(client, captureIds),
      ),
    enabled: captureIds.length > 0,
    staleTime: Infinity,
  });
}

export function useCall(captureId: string, index: number) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...RECIPES, "call", captureId, index],
    queryFn: () => unwrap(getCall(client, captureId, index)),
    staleTime: Infinity,
  });
}

/** The capture's HAR, read when it is downloaded. */
export function useHarExport() {
  const client = useApiClient();
  return useMutation({
    mutationFn: (captureId: string) => unwrap(getHar(client, captureId)),
  });
}
