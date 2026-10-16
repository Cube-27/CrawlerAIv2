import { Button } from "@heroui/react";
import { useSubmitExtract } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { ExtractRequest } from "../../../api/jobs";
import { useFieldsReview } from "../fields/useFieldsReview";
import { SchemaSelect } from "../../../components/SchemaSelect";
import { optionsChanged, withSchema } from "../pageRequest";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobModeOutput } from "../run/JobRun";
import { useShownJob } from "../run/useShownJob";
import { requestUrl, UrlInput } from "../UrlInput";
import { usePageForm } from "../usePageForm";
import { ExtractOptions } from "./ExtractOptions";
import {
  buildExtract,
  DEFAULT_EXTRACT_OPTIONS,
  extractErrors,
  extractForm,
  INITIAL_EXTRACT,
} from "./form";

/** The Extract playground at `/extract` (SPEC-14 §4.2): a URL (more URLs and globs in the options), a schema (stored,
 * inline or from a prompt) and its page kind (`POST /v1/extract`), and the run on the page (`?job=`) as Batch's
 * results table; before any run, the recent extracts. */
export function ExtractPlayground() {
  const submit = useSubmitExtract();
  const problem = problemOf(submit.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_EXTRACT,
    problem,
    extractErrors,
  );
  const { jobId, onEdit, show } = useShownJob(extractForm, setForm);

  const request = buildExtract({ ...form, url: requestUrl(form.url) });
  const review = useFieldsReview((sent: ExtractRequest) => {
    submit.mutate(sent, { onSuccess: show });
  });
  const start = () => {
    if (!check() || request === null) return;
    review.start(request, request.page_kind);
  };

  return (
    <PlaygroundLayout
      mode="extract"
      validationErrors={validationErrors}
      onSubmit={start}
      onEdit={onEdit}
      request={request}
      input={
        <UrlInput
          value={form.url}
          onChange={(url) => {
            setForm({ ...form, url });
          }}
        />
      }
      optionsOpen={optionsOpen}
      onOptionsOpen={setOptionsOpen}
      optionsChanged={optionsChanged(form.options, DEFAULT_EXTRACT_OPTIONS)}
      tools={
        <SchemaSelect
          value={form.schemaId}
          noneLabel="No schema"
          hideLabel
          isDisabled={form.options.schemaSource !== "id"}
          onChange={(schemaId, schema) => {
            setForm(withSchema(form, schemaId, schema?.page_kind ?? null));
          }}
        />
      }
      action={
        <Button type="submit" isPending={submit.isPending}>
          Extract
        </Button>
      }
      options={
        <ExtractOptions
          options={form.options}
          schemaPageKind={form.schemaPageKind}
          onChange={(options) => {
            setForm({ ...form, options });
          }}
        />
      }
    >
      <JobModeOutput
        kind="extract"
        starting={submit.isPending ? "Starting the extract" : null}
        problem={problem}
        jobId={jobId}
        withMetadata={false}
      />
      {review.drawer}
    </PlaygroundLayout>
  );
}
