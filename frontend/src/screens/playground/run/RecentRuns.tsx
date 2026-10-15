import { Typography } from "@heroui/react";
import { useJobs } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { JobKind } from "../../../api/jobs";
import { LoadingView } from "../../../components/LoadingView";
import { ProblemAlert } from "../../../components/ProblemAlert";
import { JobRows } from "../../jobs/JobRows";

/** How many runs the list shows (SPEC-14 §4.6). */
const RECENT = 10;

/** Recent runs' columns and their widths. */
const RUN_COLUMNS = [
  ["run", "w-1/2"],
  ["status", "w-1/4"],
  ["started", "w-1/4"],
] as const;

/** The last runs of a mode's `kind` (SPEC-14 §4.6), newest first, shown before any run on the page; a row opens its
 * run here (`?job=`). Every state fills the output area's box, so a run that replaces the list moves nothing. */
export function RecentRuns({ kind }: Readonly<{ kind: JobKind }>) {
  const jobs = useJobs({ filters: { kind, status: null }, cursor: null, limit: RECENT });
  const problem = problemOf(jobs.error);
  let content;
  if (problem !== null) content = <ProblemAlert problem={problem} />;
  else if (jobs.isSuccess)
    content = (
      <JobRows
        label="Recent runs"
        jobs={jobs.data.items}
        columns={RUN_COLUMNS}
        empty="No runs yet."
      />
    );
  else content = <LoadingView label="Loading recent runs" />;
  return (
    <section aria-label="Recent runs" className="flex min-h-playground-output flex-col gap-3">
      <Typography.Heading level={2}>Recent runs</Typography.Heading>
      {content}
    </section>
  );
}
