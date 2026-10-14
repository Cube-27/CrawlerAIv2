import { Fieldset } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useSubmitCrawl } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { FormatChoices } from "../../components/FormatChoices";
import { LimitField } from "../../components/LimitField";
import { buildCrawl, INITIAL_CRAWL, type CrawlFormState } from "./form";
import { JobDialog } from "./JobDialog";
import { FetchFields, JobSchemaFields, LinesField, UrlField } from "./JobFields";
import { JobForm } from "./JobForm";
import { PageKindRules } from "./PageKindRules";
import { jobPath } from "./paths";

type Edit = (change: Partial<CrawlFormState>) => void;

/** Where the crawl may go: its globs, depth and page limit. */
function ScopeFields({ form, edit }: Readonly<{ form: CrawlFormState; edit: Edit }>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Scope</Fieldset.Legend>
      <LinesField
        label="Include"
        name="include"
        description="URL globs, one per line. Empty: the start URL's host."
        value={form.include}
        onChange={(include) => {
          edit({ include });
        }}
      />
      <LinesField
        label="Exclude"
        name="exclude"
        description="URL globs, one per line, left out of the crawl."
        value={form.exclude}
        onChange={(exclude) => {
          edit({ exclude });
        }}
      />
      <LimitField
        label="Max depth"
        name="max_depth"
        value={form.maxDepth}
        minValue={0}
        onChange={(maxDepth) => {
          edit({ maxDepth });
        }}
      />
      <LimitField
        label="Page limit"
        name="limit"
        value={form.limit}
        minValue={1}
        onChange={(limit) => {
          edit({ limit });
        }}
      />
    </Fieldset>
  );
}

function CrawlForm({ onCancel }: Readonly<{ onCancel: () => void }>) {
  const navigate = useNavigate();
  const [form, setForm] = useState<CrawlFormState>(INITIAL_CRAWL);
  const edit: Edit = (change) => {
    setForm({ ...form, ...change });
  };
  const submit = useSubmitCrawl();
  return (
    <JobForm
      submitLabel="Queue crawl"
      problem={problemOf(submit.error)}
      isPending={submit.isPending}
      onCancel={onCancel}
      onSubmit={() => {
        const request = buildCrawl(form);
        if (request === null) return;
        submit.mutate(request, { onSuccess: (id) => void navigate(jobPath(id)) });
      }}
    >
      <UrlField
        label="Start URL"
        name="url"
        value={form.url}
        onChange={(url) => {
          edit({ url });
        }}
      />
      <FormatChoices
        value={form.formats}
        onChange={(formats) => {
          edit({ formats });
        }}
      />
      <JobSchemaFields
        value={form.schema}
        onChange={(schema) => {
          edit({ schema });
        }}
      />
      <PageKindRules
        rules={form.rules}
        onChange={(rules) => {
          edit({ rules });
        }}
      />
      <ScopeFields form={form} edit={edit} />
      <FetchFields methodHint={form.methodHint} webhookUrl={form.webhookUrl} onChange={edit} />
    </JobForm>
  );
}

/** `POST /v1/crawl` (SPEC-10 §4.5): a crawl from one start URL. */
export function CrawlDialog() {
  return (
    <JobDialog label="New crawl" title="New crawl">
      {(close) => <CrawlForm onCancel={close} />}
    </JobDialog>
  );
}
