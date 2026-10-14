import { Button, Description, Form, Input, Label, TextField } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { BatchDialog } from "./BatchDialog";
import { CrawlDialog } from "./CrawlDialog";
import { ExtractDialog } from "./ExtractDialog";
import { MapDialog } from "./MapDialog";
import { jobPath } from "./paths";

/** Starts batch scrapes, crawls, extracts and maps, and opens a job by id. The API reads jobs one at a time
 * (`GET /v1/jobs/{id}`) and has no list of jobs, so a job is opened by its id; a new job opens on its own. */
export function JobsScreen() {
  const navigate = useNavigate();
  const [id, setId] = useState("");
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        title="Jobs"
        actions={
          <>
            <MapDialog />
            <CrawlDialog />
            <ExtractDialog />
            <BatchDialog />
          </>
        }
      />
      <Form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void navigate(jobPath(id.trim()));
        }}
      >
        <TextField isRequired value={id} onChange={setId}>
          <Label>Job ID</Label>
          <Input autoComplete="off" spellCheck={false} />
          <Description>The id a job was created with.</Description>
        </TextField>
        <FormActions>
          <Button type="submit">Open job</Button>
        </FormActions>
      </Form>
    </section>
  );
}
