import { useState } from "react";
import { useSearchParams } from "react-router";
import { useJobRequest } from "../../../api/hooks/jobs";
import { JOB } from "./jobParam";
import type { StoredJobRequest } from "../../../api/jobs";

/** The run a mode's page shows from `?job=`. Once its stored request loads, it fills the form (`formOf`, `setForm`);
 * a job of another kind than the mode's (`formOf` gives null) leaves it as it is. The page is read-only until `edit`;
 * "Edit and re-run" then starts a new job, and the old one is kept. `show` puts a new run in the address, `clear` takes
 * the run out of it. */
export function useShownJob<F>(
  formOf: (stored: StoredJobRequest) => F | null,
  setForm: (form: F) => void,
) {
  const [params, setParams] = useSearchParams();
  const jobId = params.get(JOB);
  const stored = useJobRequest(jobId).data;
  // The job whose request is in the form, and whether it is being edited.
  const [shown, setShown] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const form = stored !== undefined && jobId !== null && jobId !== shown ? formOf(stored) : null;
  if (form !== null && jobId !== null) {
    // React's "adjusting state when a prop changes": the form follows the job in the same render.
    setShown(jobId);
    setEditing(false);
    setForm(form);
  }
  return {
    jobId,
    /** Null unless the page shows a run's request read-only; then it makes the request editable. */
    onEdit:
      jobId !== null && !editing
        ? () => {
            setEditing(true);
          }
        : null,
    show: (id: string) => {
      setParams({ [JOB]: id });
    },
    clear: () => {
      setParams({});
    },
  };
}
