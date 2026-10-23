import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import { captureCalls, captureSample, getCall, getHar, type CaptureRequest } from "../captures";
import {
  proposeRecipe,
  recipeCalls,
  saveRecipe,
  testRecipe,
  type CustomRecipe,
  type ProposeBody,
} from "../recipes";
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

/** The draft `body` asks for; none while it is null (no main call chosen). Proposing is deterministic and stores
 * nothing, so one draft per choice is read once; the last draft stays while the next is read. */
export function useProposal(body: ProposeBody | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...RECIPES, "propose", body],
    queryFn: () =>
      body === null
        ? Promise.reject(new Error("no main call"))
        : unwrap(proposeRecipe(client, body)),
    enabled: body !== null,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
  });
}

/** A draft of another endpoint, made when it is added as an extra call. */
export function useProposeCall() {
  const client = useApiClient();
  return useMutation({
    mutationFn: (body: ProposeBody) => unwrap(proposeRecipe(client, body)),
  });
}

/** A test fetches the URLs anew each time and stores nothing. */
export function useTestRecipe() {
  const client = useApiClient();
  return useMutation({
    mutationFn: (body: { recipe: CustomRecipe; urls: string[] }) =>
      unwrap(testRecipe(client, body)),
  });
}

/** Saves the recipe, new or as the next version of `replaces`; every config is read again, as a correction's are. */
export function useSaveRecipe(host: string, replaces: string | null) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (recipe: CustomRecipe) => unwrap(saveRecipe(client, host, recipe, replaces)),
    onSuccess: (saved) => {
      queryClient.setQueryData(["configs", "one", saved.id], saved);
      return queryClient.invalidateQueries({ queryKey: ["configs"] });
    },
  });
}
