import { Fieldset } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useSubmitExtract } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { Choices } from "../../components/Choices";
import { LimitField } from "../../components/LimitField";
import { PAGE_KINDS } from "../../components/requestOptions";
import { buildExtract, INITIAL_EXTRACT, type ExtractFormState } from "./form";
import { JobDialog } from "./JobDialog";
import { EXTRACT_SCHEMA_SOURCES, FetchFields, JobSchemaFields, LinesField } from "./JobFields";
import { JobForm } from "./JobForm";
import { jobPath } from "./paths";

type Edit = (change: Partial<ExtractFormState>) => void;

function LimitFields({ form, edit }: Readonly<{ form: ExtractFormState; edit: Edit }>) {
  return (
    <Fieldset>
      <Fieldset.Legend>Limits</Fieldset.Legend>
      <LimitField
        label="URL limit"
        name="limit"
        value={form.limit}
        minValue={1}
        onChange={(limit) => {
          edit({ limit });
        }}
      />
      <LimitField
        label="LLM call budget"
        name="budget"
        value={form.llmCalls}
        minValue={0}
        onChange={(llmCalls) => {
          edit({ llmCalls });
        }}
      />
    </Fieldset>
  );
}

function ExtractForm({ onCancel }: Readonly<{ onCancel: () => void }>) {
  const navigate = useNavigate();
  const [form, setForm] = useState<ExtractFormState>(INITIAL_EXTRACT);
  const edit: Edit = (change) => {
    setForm({ ...form, ...change });
  };
  const submit = useSubmitExtract();
  return (
    <JobForm
      submitLabel="Queue extract"
      problem={problemOf(submit.error)}
      isPending={submit.isPending}
      onCancel={onCancel}
      onSubmit={() => {
        const request = buildExtract(form);
        if (request === null) return;
        submit.mutate(request, { onSuccess: (id) => void navigate(jobPath(id)) });
      }}
    >
      <LinesField
        label="URLs"
        name="urls"
        description="One URL per line; a URL with * is a glob over its site's map."
        isRequired
        value={form.urls}
        onChange={(urls) => {
          edit({ urls });
        }}
      />
      <JobSchemaFields
        sources={EXTRACT_SCHEMA_SOURCES}
        value={form.schema}
        onChange={(schema) => {
          edit({ schema });
        }}
      />
      <Choices
        label="Page kind"
        name="page_kind"
        options={PAGE_KINDS}
        value={form.pageKind}
        isRequired
        onChange={(pageKind) => {
          edit({ pageKind });
        }}
      />
      <LimitFields form={form} edit={edit} />
      <FetchFields methodHint={form.methodHint} webhookUrl={form.webhookUrl} onChange={edit} />
    </JobForm>
  );
}

/** `POST /v1/extract` (SPEC-10 §4.6): records of one page kind from URLs and globs, with a schema or a prompt. */
export function ExtractDialog() {
  return (
    <JobDialog label="New extract" title="New extract">
      {(close) => <ExtractForm onCancel={close} />}
    </JobDialog>
  );
}
