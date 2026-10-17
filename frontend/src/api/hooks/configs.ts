import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  approveConfig,
  correctConfig,
  exportConfig,
  getConfig,
  learnSite,
  listSiteConfigs,
  rejectConfig,
  type Correction,
  type ExportFormat,
} from "../configs";
import { unwrap } from "./query";

/** The site config endpoints as TanStack Query hooks. Every key starts with `configs`, so a correction reads them all
 * again: the server's new version, not a local patch. */
const CONFIGS = ["configs"] as const;

/** Every version of the site's configs. */
export function useSiteConfigs(host: string) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...CONFIGS, "site", host],
    queryFn: () => unwrap(listSiteConfigs(client, host)),
  });
}

export function useConfig(id: string) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...CONFIGS, "one", id],
    queryFn: () => unwrap(getConfig(client, id)),
  });
}

export function useCorrectConfig(id: string) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Correction) => unwrap(correctConfig(client, id, body)),
    // The answer is the new version: opening it needs no read. The other versions' statuses may have changed.
    onSuccess: (saved) => {
      queryClient.setQueryData([...CONFIGS, "one", saved.id], saved);
      return queryClient.invalidateQueries({ queryKey: CONFIGS });
    },
  });
}

/** A person's decision on a config waiting for approval: the answer is that version, and the version active before it
 * may be suspended, so every config is read again. */
function useDecideConfig(decide: typeof approveConfig, id: string) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(decide(client, id)),
    onSuccess: (decided) => {
      queryClient.setQueryData([...CONFIGS, "one", decided.id], decided);
      return queryClient.invalidateQueries({ queryKey: CONFIGS });
    },
  });
}

/** Approves the config: it becomes the active version. */
export function useApproveConfig(id: string) {
  return useDecideConfig(approveConfig, id);
}

/** Rejects the config: it is suspended. */
export function useRejectConfig(id: string) {
  return useDecideConfig(rejectConfig, id);
}

/** An export changes nothing on the server, so nothing is read again. */
export function useExportConfig(id: string) {
  const client = useApiClient();
  return useMutation({
    mutationFn: (format: ExportFormat) => unwrap(exportConfig(client, id, format)),
  });
}

/** Learning runs as a job; the configs it makes appear when it ends, so nothing is read again now. */
export function useLearnSite(host: string) {
  const client = useApiClient();
  return useMutation({
    mutationFn: (body: { schema_id: string; force: boolean }) =>
      unwrap(learnSite(client, host, body)),
  });
}
