import { Button } from "@heroui/react";
import { useSearchParams } from "react-router";
import { useSubmitBatch } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { OutputArea } from "../OutputArea";
import { pageKindErrors, requestPageKind } from "../pageRequest";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JOB } from "../run/jobParam";
import { JobRunOutput } from "../run/JobRun";
import { usePageForm } from "../usePageForm";
import { BatchOptions } from "./BatchOptions";
import { buildBatch, DEFAULT_BATCH_OPTIONS, INITIAL_BATCH } from "./form";
import { UrlList } from "./UrlList";

/** The Batch playground at `/batch` (SPEC-14 §4.2): a URL list, the same formats, schema and options for every URL
 * (`POST /v1/batch/scrape`), and the run on the same page as a running results table. */
export function BatchPlayground() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get(JOB);
  const submit = useSubmitBatch();
  const problem = problemOf(submit.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_BATCH,
    problem,
    pageKindErrors,
  );

  const start = () => {
    const request = check() ? buildBatch(form) : null;
    if (request === null) return;
    submit.mutate(request, {
      onSuccess: (id) => {
        setParams({ [JOB]: id });
      },
    });
  };

  let output = null;
  if (submit.isPending)
    output = <OutputArea state={{ kind: "pending", label: "Starting the batch" }} />;
  else if (problem !== null) output = <OutputArea state={{ kind: "failed", problem }} />;
  else if (jobId !== null)
    output = <JobRunOutput key={jobId} jobId={jobId} withMetadata={form.options.metadataInJson} />;

  return (
    <PlaygroundLayout
      mode="batch"
      validationErrors={validationErrors}
      onSubmit={start}
      input={
        <UrlList
          value={form.urls}
          onChange={(urls) => {
            setForm({ ...form, urls });
          }}
        />
      }
      tools={
        <PageTools
          form={form}
          defaults={DEFAULT_BATCH_OPTIONS}
          optionsOpen={optionsOpen}
          onOptionsOpen={setOptionsOpen}
          onChange={setForm}
        />
      }
      action={
        <Button type="submit" isPending={submit.isPending}>
          Start batch
        </Button>
      }
      options={
        optionsOpen ? (
          <BatchOptions
            options={form.options}
            hasSchema={form.schemaId !== ""}
            schemaPageKind={requestPageKind(form)}
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
