import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  correctConfig,
  exportConfig,
  getConfig,
  learnSite,
  listSiteConfigs,
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: CONFIGS }),
  });
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
