import { useNavigate } from "react-router";
import { LookupForm } from "../../components/LookupForm";
import { PageHeader } from "../../components/PageHeader";
import { CrawlDialog } from "./CrawlDialog";
import { ExtractDialog } from "./ExtractDialog";
import { JobTable } from "./JobTable";
import { MapDialog } from "./MapDialog";
import { jobPath } from "./paths";

/** Starts crawls, extracts and maps, lists the jobs (SPEC-12 §4.3), and opens a job by its id. A new
 * job opens on its own page. */
export function JobsScreen() {
  const navigate = useNavigate();
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        title="Jobs"
        description="Batch scrapes, crawls, maps and extracts, newest first."
        actions={
          <>
            <MapDialog />
            <CrawlDialog />
            <ExtractDialog />
          </>
        }
      />
      <LookupForm
        label="Job ID"
        placeholder="Paste a job id"
        submitLabel="Open job"
        onOpen={(id) => void navigate(jobPath(id))}
      />
      <JobTable />
    </section>
  );
}
