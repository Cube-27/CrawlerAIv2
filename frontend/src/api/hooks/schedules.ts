import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import {
  createSchedule,
  deleteSchedule,
  getSchedule,
  listSchedules,
  runSchedule,
  setSchedulePaused,
  type NewSchedule,
} from "../schedules";
import { unwrap } from "./query";

/** `/v1/schedules` as TanStack Query hooks. Every key starts with `schedules`, so one change reads them all again; a
 * run now also reads the jobs again. */
const SCHEDULES = ["schedules"] as const;

export function useSchedules(page: { cursor: string | null; limit: number }) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...SCHEDULES, "list", page],
    queryFn: () => unwrap(listSchedules(client, page)),
  });
}

export function useSchedule(id: string) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...SCHEDULES, "one", id],
    queryFn: () => unwrap(getSchedule(client, id)),
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: SCHEDULES });
    await queryClient.invalidateQueries({ queryKey: ["jobs"] });
  };
}

export function useCreateSchedule() {
  const client = useApiClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: NewSchedule) => unwrap(createSchedule(client, body)),
    onSuccess: invalidate,
  });
}

export function useSetSchedulePaused() {
  const client = useApiClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, paused }: { id: string; paused: boolean }) =>
      unwrap(setSchedulePaused(client, id, paused)),
    onSuccess: invalidate,
  });
}

export function useRunSchedule() {
  const client = useApiClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => unwrap(runSchedule(client, id)),
    onSuccess: invalidate,
  });
}

export function useDeleteSchedule() {
  const client = useApiClient();
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => unwrap(deleteSchedule(client, id)),
    onSuccess: invalidate,
  });
}
