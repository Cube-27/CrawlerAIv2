import { useState } from "react";
import { useSearchParams } from "react-router";
import { useJobRequest } from "../../../api/hooks/jobs";
import { JOB } from "./jobParam";
import type { StoredRequest } from "./storedRequest";

/** The run a mode's page shows from `?job=` (SPEC-14 §4.8). Once its stored request loads, it fills the form
 * (`formOf`, `setForm`) and the page is read-only until `edit`; "Edit and re-run" then starts a new job, and the old one
 * is kept. `show` puts a new run in the address, `clear` takes the run out of it. */
export function useShownJob<F>(formOf: (request: StoredRequest) => F, setForm: (form: F) => void) {
  const [params, setParams] = useSearchParams();
  const jobId = params.get(JOB);
  const request = useJobRequest(jobId).data;
  // The job whose request is in the form, and whether it is being edited.
  const [shown, setShown] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  if (request !== undefined && jobId !== null && jobId !== shown) {
    // React's "adjusting state when a prop changes": the form follows the job in the same render.
    setShown(jobId);
    setEditing(false);
    setForm(formOf(request));
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
