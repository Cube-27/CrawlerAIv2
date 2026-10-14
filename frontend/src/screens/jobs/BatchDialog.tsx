import { Fieldset } from "@heroui/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { useSubmitBatch } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { Choices } from "../../components/Choices";
import { FormatChoices } from "../../components/FormatChoices";
import { METHOD_HINTS, PAGE_KINDS } from "../../components/requestOptions";
import { buildBatch, INITIAL_BATCH, type BatchFormState } from "./form";
import { JobDialog } from "./JobDialog";
import { JobSchemaFields, LinesField, UrlField } from "./JobFields";
import { JobForm } from "./JobForm";
import { jobPath } from "./paths";

function BatchForm({ onCancel }: Readonly<{ onCancel: () => void }>) {
  const navigate = useNavigate();
  const [form, setForm] = useState<BatchFormState>(INITIAL_BATCH);
  const submit = useSubmitBatch();
  return (
    <JobForm
      submitLabel="Queue batch"
      problem={problemOf(submit.error)}
      isPending={submit.isPending}
      onCancel={onCancel}
      onSubmit={() => {
        const request = buildBatch(form);
        if (request === null) return;
        submit.mutate(request, { onSuccess: (id) => void navigate(jobPath(id)) });
      }}
    >
      <LinesField
        label="URLs"
        name="urls"
        description="One URL per line."
        isRequired
        value={form.urls}
        onChange={(urls) => {
          setForm({ ...form, urls });
        }}
      />
      <FormatChoices
        value={form.formats}
        onChange={(formats) => {
          setForm({ ...form, formats });
        }}
      />
      <JobSchemaFields
        value={form.schema}
        onChange={(schema) => {
          setForm({ ...form, schema });
        }}
      />
      {/* SPEC-07 §4.4: `page_kind` is required when the formats include records. */}
      <Choices
        label="Page kind"
        name="page_kind"
        options={PAGE_KINDS}
        value={form.pageKind}
        isRequired={form.formats.includes("records")}
        onChange={(pageKind) => {
          setForm({ ...form, pageKind });
        }}
      />
      <Fieldset>
        <Fieldset.Legend>Fetch and notification</Fieldset.Legend>
        <Choices
          label="Fetch method"
          options={METHOD_HINTS}
          value={form.methodHint}
          onChange={(methodHint) => {
            setForm({ ...form, methodHint });
          }}
        />
        <UrlField
          label="Webhook URL"
          name="webhook_url"
          isRequired={false}
          value={form.webhookUrl}
          onChange={(webhookUrl) => {
            setForm({ ...form, webhookUrl });
          }}
        />
      </Fieldset>
    </JobForm>
  );
}

/** `POST /v1/batch/scrape` (SPEC-10 §4.3): the same formats, schema and fetch options for every URL. */
export function BatchDialog() {
  return (
    <JobDialog label="New batch" title="New batch scrape">
      {(close) => <BatchForm onCancel={close} />}
    </JobDialog>
  );
}
