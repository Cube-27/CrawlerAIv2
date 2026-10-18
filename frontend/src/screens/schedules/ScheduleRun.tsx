import { useJobRequest } from "../../api/hooks/jobs";
import type { JobSummary } from "../../api/jobs";
import { RUN_SCHEDULE_KINDS } from "./cadence";
import { ScheduleDialog } from "./ScheduleDialog";

/** Schedule this run (D-1514): a run's stored request (`GET /v1/jobs/{id}/request`, its caller secrets shown as
 * `**********`) as a recurring schedule. Nothing for a kind that cannot be scheduled; off until the request is read. */
export function ScheduleRun({ job }: Readonly<{ job: JobSummary }>) {
  const request = useJobRequest(job.id);
  const kind = RUN_SCHEDULE_KINDS[job.kind];
  if (kind === undefined) return null;
  return <ScheduleDialog kind={kind} request={request.data ?? null} label="Schedule this run" />;
}
