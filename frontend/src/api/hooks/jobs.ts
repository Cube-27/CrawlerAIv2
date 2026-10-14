import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  cancelJob,
  exportJobPage,
  getJob,
  listJobResults,
  mapUrls,
  submitBatch,
  submitCrawl,
  type BatchRequest,
  type CrawlRequest,
  type ExportFormat,
  type ExportPage,
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

export function useJob(id: string) {
  const client = useApiClient();
  return useQuery({ queryKey: jobKey(id), queryFn: () => unwrap(getJob(client, id)) });
}

/** The job's results at `cursor`. */
export function useJobResults(id: string, cursor: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...jobResultsKey(id), cursor],
    queryFn: () => unwrap(listJobResults(client, id, cursor)),
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

/** A new job: nothing read before shows it, so nothing is read again. */
export function useSubmitBatch() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: BatchRequest) => unwrap(submitBatch(client, body)) });
}

export function useSubmitCrawl() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: CrawlRequest) => unwrap(submitCrawl(client, body)) });
}

/** A map changes nothing on the server. */
export function useMapUrls() {
  const client = useApiClient();
  return useMutation({ mutationFn: (body: MapRequest) => unwrap(mapUrls(client, body)) });
}
