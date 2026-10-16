import { Button, toast } from "@heroui/react";
import { ArrowDownToLine } from "@gravity-ui/icons";
import { useExportJob, useExportJobValues } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { saveExportPages, saveJson } from "../../../app/download";

// RFC 4180 §3: CSV's media type.
const CSV = { extension: "csv", type: "text/csv" };

/** A refused export, as a toast: it is the outcome of the button just pressed, and an alert in the run's header moved
 * the page under it (D-0979). */
function notifyRefused(error: Error) {
  const problem = problemOf(error);
  toast.danger(problem?.title ?? "The export failed.", {
    description: problem?.detail ?? undefined,
  });
}

/** A run's downloads (SPEC-14 §4.3–4.4): JSON is every page's `json_values` item in task order, saved as one array, so
 * it equals the drawers' items; CSV is the server's `csv_records` export (RFC 4180), one file per page of it. A job
 * without a schema has no records to export as CSV; the server's problem says so. */
export function RunExports({
  jobId,
  withMetadata,
}: Readonly<{ jobId: string; withMetadata: boolean }>) {
  const json = useExportJobValues(jobId);
  const csv = useExportJob(jobId);
  const busy = json.isPending || csv.isPending;
  return (
    <div className="flex gap-2">
      <Button
        variant="secondary"
        isPending={json.isPending}
        isDisabled={busy}
        onPress={() => {
          json.mutate(withMetadata, {
            onSuccess: (items) => {
              const filename = `job-${jobId}.json`;
              saveJson(filename, items);
              toast.success(`Saved ${filename}.`);
            },
            onError: notifyRefused,
          });
        }}
      >
        <ArrowDownToLine aria-hidden="true" />
        Export JSON
      </Button>
      <Button
        variant="secondary"
        isPending={csv.isPending}
        isDisabled={busy}
        onPress={() => {
          csv.mutate("csv_records", {
            onSuccess: (pages) => {
              const files = saveExportPages(jobId, CSV, pages);
              toast.success(`Saved ${files.join(", ")}.`);
            },
            onError: notifyRefused,
          });
        }}
      >
        <ArrowDownToLine aria-hidden="true" />
        Export CSV
      </Button>
    </div>
  );
}
