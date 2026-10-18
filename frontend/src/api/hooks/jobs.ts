import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  cancelJob,
  exportJobOutputs,
  exportJobPage,
  exportJobValues,
  exportJobFile,
  getJob,
  getJobRequest,
  listJobs,
  listJobResults,
  listJobValues,
  listWebhookDeliveries,
  mapUrls,
  searchWeb,
  submitBatch,
  submitCrawl,
  submitExtract,
  type BatchRequest,
  type CrawlRequest,
  type ExtractRequest,
  type ExportFormat,
  type JobFile,
  type ValuesPage,
  type ExportPage,
  type JobFilters,
  type MapRequest,
  type SearchRequest,
} from "../jobs";
import { unwrap } from "./query";

/** The job endpoints as TanStack Query hooks. Every key starts with `jobs`, so a job's end reads its summary and
 * results again. */
const JOBS = ["jobs"] as const;

/** How often a page with a pending delivery is read again: the scheduler tries deliveries every few seconds. */
const DELIVERY_POLL_MS = 5000;

export function jobKey(id: string) {
  return [...JOBS, "one", id] as const;
}

export function jobResultsKey(id: string) {
  return [...JOBS, "results", id] as const;
}

/** The page of the jobs that pass `filters` at `cursor`. */
export function useJobs(page: { filters: JobFilters; cursor: string | null; limit: number }) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...JOBS, "list", page],
    queryFn: () => unwrap(listJobs(client, page)),
  });
}

/** The job `id`; nothing is read while `id` is null. */
export function useJob(id: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: jobKey(id ?? ""),
    queryFn: () => unwrap(getJob(client, id ?? "")),
    enabled: id !== null,
  });
}

/** The job's stored request; nothing is read while `id` is null. It never changes, so it is read once. */
export function useJobRequest(id: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...JOBS, "request", id],
    queryFn: () => unwrap(getJobRequest(client, id ?? "")),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

/** The job's results at `cursor`; nothing is read unless `enabled`. */
export function useJobResults(
  id: string,
  page: { cursor: string | null; limit: number },
  enabled = true,
) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...jobResultsKey(id), page],
    queryFn: () => unwrap(listJobResults(client, id, page)),
    enabled,
  });
}

/** The job's webhook deliveries at `cursor`. A delivery still pending is read again every few seconds, until none is. */
export function useWebhookDeliveries(id: string, page: { cursor: string | null; limit: number }) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...JOBS, "webhook-deliveries", id, page],
    queryFn: () => unwrap(listWebhookDeliveries(client, id, page)),
    refetchInterval: (query) =>
      query.state.data?.items.some((delivery) => delivery.status === "pending")
        ? DELIVERY_POLL_MS
        : false,
  });
}

/** The job's `json_values` page at `cursor`. Under the results key, so the job's events read it again; the page shown
 * stays while it is read again. */
export function useJobValues(id: string, page: ValuesPage, enabled = true) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...jobResultsKey(id), "json_values", page],
    queryFn: () => unwrap(listJobValues(client, id, page)),
    enabled,
  });
}

/** The job's JSON download (frontend spec): every `json_values` item, or with `outputs` (a job without a schema)
 * every page output. */
export function useExportJobJson(id: string, outputs: boolean) {
  const client = useApiClient();
  return useMutation({
    mutationFn: (withMetadata: boolean): Promise<unknown[]> =>
      outputs
        ? unwrap(exportJobOutputs(client, id))
        : unwrap(exportJobValues(client, id, withMetadata)),
  });
}

/** The answer is the job after the cancel: shown without a read. */
export function useCancelJob(id: string) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(cancelJob(client, id)),
    onSuccess: (job) => {
      queryClient.setQueryData(jobKey(id), job);
    },
  });
}

/** Every page of the job's records in `format`, read in turn by cursor. Each page is a whole document (with its own
 * CSV header or JSON array), so the pages are kept apart. */
export function useExportJob(id: string) {
  const client = useApiClient();
  return useMutation({
    mutationFn: async (format: ExportFormat) => {
      const pages: ExportPage[] = [];
      let cursor: string | null = null;
      do {
        const page: ExportPage = await unwrap(exportJobPage(client, id, format, cursor));
        pages.push(page);
        cursor = page.next_cursor;
      } while (cursor !== null);
      return pages;
    },
  });
}

/** The job as one file (`exportJobFile`). */
export function useExportJobFile(id: string) {
  const client = useApiClient();
  return useMutation({ mutationFn: (file: JobFile) => unwrap(exportJobFile(client, id, file)) });
}

/** A new job: nothing read before shows it, so nothing is read again. */
export function useSubmitBatch() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: BatchRequest) => unwrap(submitBatch(client, body)) });
}

export function useSubmitCrawl() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: CrawlRequest) => unwrap(submitCrawl(client, body)) });
}

export function useSubmitExtract() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: ExtractRequest) => unwrap(submitExtract(client, body)) });
}

/** A map changes nothing on the server. */
export function useMapUrls() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: MapRequest) => unwrap(mapUrls(client, body)) });
}

/** A search changes nothing on the server unless it scrapes: the batch job it queues is read through its own hooks. */
export function useSearchWeb() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: SearchRequest) => unwrap(searchWeb(client, body)) });
}
