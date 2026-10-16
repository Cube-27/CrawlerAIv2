import { useNavigate } from "react-router";
import { LookupForm } from "../../components/LookupForm";
import { PageHeader } from "../../components/PageHeader";
import { JobTable } from "./JobTable";
import { jobPath } from "./paths";

/** The run history (SPEC-14 §4.8, SPEC-12 §4.3): every job, newest first, a row opening its run in its playground
 * mode; a job also opens by its id. Runs start in the playground. */
export function JobsScreen() {
  const navigate = useNavigate();
  return (
    <section className="flex flex-col gap-stack">
      <PageHeader
        title="Jobs"
        description="Every run, newest first. Open a row to see its results in the playground."
      />
      <JobTable
        tools={
          <LookupForm
            label="Job ID"
            placeholder="Paste a job id"
            submitLabel="Open job"
            onOpen={(id) => void navigate(jobPath(id))}
          />
        }
      />
    </section>
  );
}
