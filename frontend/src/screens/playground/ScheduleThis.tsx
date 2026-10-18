import { ScheduleDialog } from "../schedules/ScheduleDialog";
import { SCHEDULE_KINDS } from "../schedules/cadence";
import type { ModeId } from "./modes";

/** The toolbar's Schedule this button (D-1418): `request` (the body the mode's action would send; null while the form
 * can't be sent) as a recurring schedule. Map runs no queued job, so it has none. */
export function ScheduleThis({
  mode,
  request,
}: Readonly<{ mode: ModeId; request: object | null }>) {
  const kind = SCHEDULE_KINDS[mode];
  if (kind === undefined) return null;
  return <ScheduleDialog kind={kind} request={request} label="Schedule this" />;
}
