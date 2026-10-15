import { Button } from "@heroui/react";
import { useSubmitExtract } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { SchemaSelect } from "../../../components/SchemaSelect";
import { OptionsToggle } from "../OptionsPanel";
import { OutputArea } from "../OutputArea";
import { optionsChanged } from "../pageRequest";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobRunOutput } from "../run/JobRun";
import { RecentRuns } from "../run/RecentRuns";
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

  const start = () => {
    const request = check() ? buildExtract({ ...form, url: requestUrl(form.url) }) : null;
    if (request === null) return;
    submit.mutate(request, { onSuccess: show });
  };

  let output = <RecentRuns kind="extract" />;
  if (submit.isPending)
    output = <OutputArea state={{ kind: "pending", label: "Starting the extract" }} />;
  else if (problem !== null) output = <OutputArea state={{ kind: "failed", problem }} />;
  else if (jobId !== null) output = <JobRunOutput key={jobId} jobId={jobId} withMetadata={false} />;

  return (
    <PlaygroundLayout
      mode="extract"
      validationErrors={validationErrors}
      onSubmit={start}
      onEdit={onEdit}
      input={
        <UrlInput
          value={form.url}
          onChange={(url) => {
            setForm({ ...form, url });
          }}
        />
      }
      optionsToggle={
        <OptionsToggle
          isOpen={optionsOpen}
          changed={optionsChanged(form.options, DEFAULT_EXTRACT_OPTIONS)}
          onChange={setOptionsOpen}
        />
      }
      tools={
        <SchemaSelect
          value={form.schemaId}
          noneLabel="No schema"
          hideLabel
          isDisabled={form.options.schemaSource !== "id"}
          onChange={(schemaId, schema) => {
            setForm({ ...form, schemaId, schemaPageKind: schema?.page_kind ?? null });
          }}
        />
      }
      action={
        <Button type="submit" isPending={submit.isPending}>
          Extract
        </Button>
      }
      options={
        optionsOpen ? (
          <ExtractOptions
            options={form.options}
            schemaPageKind={form.schemaPageKind}
            onChange={(options) => {
              setForm({ ...form, options });
            }}
          />
        ) : null
      }
    >
      {output}
    </PlaygroundLayout>
  );
}
