import { useMutation, useQuery } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import { listRecords, replayCapture, type RecordFilters } from "../records";
import { unwrap } from "./query";

/** `GET /v1/records` and `POST /v1/captures/{id}/replay` as TanStack Query hooks. */

/** The page of records that pass `filters` at `cursor`. */
export function useRecords(page: { filters: RecordFilters; cursor: string | null; limit: number }) {
  const client = useApiClient();
  return useQuery({
    queryKey: ["records", page],
    queryFn: () => unwrap(listRecords(client, page)),
  });
}

/** A replay of one capture. It changes nothing on the server, so nothing is read again. */
export function useReplay() {
  const client = useApiClient();
  return useMutation({
    mutationFn: (captureId: string) => unwrap(replayCapture(client, captureId)),
  });
}
