import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  cancelJob,
  exportJobOutputs,
  exportJobPage,
  exportJobValues,
  getJob,
  getJobRequest,
  listJobs,
  listJobResults,
  listJobValues,
  mapUrls,
  submitBatch,
  submitCrawl,
  submitExtract,
  type BatchRequest,
  type CrawlRequest,
  type ExtractRequest,
  type ExportFormat,
  type ExportPage,
  type JobFilters,
  type MapRequest,
} from "../jobs";
import { unwrap } from "./query";

/** The job endpoints as TanStack Query hooks. Every key starts with `jobs`, so a job's end reads its summary and
 * results again. */
const JOBS = ["jobs"] as const;

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

/** The job's `json_values` page at `cursor`. Under the results key, so the job's events read it again; the page shown
 * stays while it is read again. */
export function useJobValues(
  id: string,
  page: { cursor: string | null; limit: number; withMetadata: boolean },
) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...jobResultsKey(id), "json_values", page],
    queryFn: () => unwrap(listJobValues(client, id, page)),
  });
}

/** Every `json_values` item of the job, for its JSON download (SPEC-14 §4.4). */
export function useExportJobValues(id: string) {
  const client = useApiClient();
  return useMutation({
    mutationFn: (withMetadata: boolean) => unwrap(exportJobValues(client, id, withMetadata)),
  });
}

/** Every page output of a job without a schema, for its JSON download. */
export function useExportJobOutputs(id: string) {
  const client = useApiClient();
  return useMutation({ mutationFn: () => unwrap(exportJobOutputs(client, id)) });
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
