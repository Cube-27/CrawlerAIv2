/** `/v1/schedules` (§22 "Recurring schedule storage", D-1410): recurring runs of a request, in the generated shapes. */
import type { ApiClient } from "./client";
import { apiDone, apiResult, type ApiResult } from "./result";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Schedule = Schemas["ScheduleOut"];
export type SchedulePage = Schemas["SchedulePage"];
export type ScheduleKind = Schemas["ScheduleUpdate"]["kind"] & string;

/** A new schedule as the Schedule this dialog builds it: one cadence, the request the mode's action would send. */
export interface NewSchedule {
  name: string;
  kind: ScheduleKind;
  request: object;
  cron?: string;
  interval_s?: number;
  timezone: string;
}

export function listSchedules(
  client: ApiClient,
  { cursor, limit }: { cursor: string | null; limit: number },
): Promise<ApiResult<SchedulePage>> {
  const query = { ...(cursor === null ? {} : { cursor }), limit };
  return apiResult(
    () => client.GET("/v1/schedules", { params: { query } }),
    "Listing the schedules",
  );
}

export function getSchedule(client: ApiClient, id: string): Promise<ApiResult<Schedule>> {
  return apiResult(
    () => client.GET("/v1/schedules/{schedule_id}", { params: { path: { schedule_id: id } } }),
    "Loading the schedule",
  );
}

export function createSchedule(client: ApiClient, body: NewSchedule): Promise<ApiResult<Schedule>> {
  return apiResult(
    // The generated body is a union of four request shapes; the server validates the request against its kind.
    () => client.POST("/v1/schedules", { body: body as never }),
    "Creating the schedule",
  );
}

export function setSchedulePaused(
  client: ApiClient,
  id: string,
  paused: boolean,
): Promise<ApiResult<Schedule>> {
  const params = { params: { path: { schedule_id: id } } };
  return paused
    ? apiResult(
        () => client.POST("/v1/schedules/{schedule_id}/pause", params),
        "Pausing the schedule",
      )
    : apiResult(
        () => client.POST("/v1/schedules/{schedule_id}/resume", params),
        "Resuming the schedule",
      );
}

export function runSchedule(client: ApiClient, id: string): Promise<ApiResult<{ job_id: string }>> {
  return apiResult(
    () => client.POST("/v1/schedules/{schedule_id}/run", { params: { path: { schedule_id: id } } }),
    "Running the schedule",
  );
}

export function deleteSchedule(client: ApiClient, id: string): Promise<ApiResult<null>> {
  return apiDone(
    () => client.DELETE("/v1/schedules/{schedule_id}", { params: { path: { schedule_id: id } } }),
    "Deleting the schedule",
  );
}
