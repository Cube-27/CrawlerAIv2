import { Button } from "@heroui/react";
import { useLocation } from "react-router";
import { useSubmitBatch } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { optionsChanged, pageKindErrors, requestPageKind } from "../pageRequest";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobModeOutput } from "../run/JobRun";
import { batchUrls } from "../run/scrapeAsBatch";
import { useShownJob } from "../run/useShownJob";
import { usePageForm } from "../usePageForm";
import { BatchOptions } from "./BatchOptions";
import { batchForm, buildBatch, DEFAULT_BATCH_OPTIONS, initialBatch } from "./form";
import { UrlList } from "./UrlList";

/** The Batch playground at `/batch` (SPEC-14 §4.2): a URL list, the same formats, schema and options for every URL
 * (`POST /v1/batch/scrape`), and the run on the same page (`?job=`) as a running results table; before any run, the
 * recent batches. URLs selected in a Map or Crawl result arrive in the navigation's state as the list. */
export function BatchPlayground() {
  // react-router types a navigation's state as `any`; `batchUrls` checks it.
  const state: unknown = useLocation().state;
  const submit = useSubmitBatch();
  const problem = problemOf(submit.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    initialBatch(batchUrls(state)),
    problem,
    pageKindErrors,
  );
  const { jobId, onEdit, show } = useShownJob(batchForm, setForm);

  const start = () => {
    const request = check() ? buildBatch(form) : null;
    if (request === null) return;
    submit.mutate(request, { onSuccess: show });
  };

  return (
    <PlaygroundLayout
      mode="batch"
      validationErrors={validationErrors}
      onSubmit={start}
      onEdit={onEdit}
      input={
        <UrlList
          value={form.urls}
          onChange={(urls) => {
            setForm({ ...form, urls });
          }}
        />
      }
      optionsOpen={optionsOpen}
      onOptionsOpen={setOptionsOpen}
      optionsChanged={optionsChanged(form.options, DEFAULT_BATCH_OPTIONS)}
      tools={<PageTools form={form} onChange={setForm} />}
      action={
        <Button type="submit" isPending={submit.isPending}>
          Start batch
        </Button>
      }
      options={
        <BatchOptions
          options={form.options}
          hasSchema={form.schemaId !== ""}
          schemaPageKind={requestPageKind(form)}
          onChange={(options) => {
            setForm({ ...form, options });
          }}
        />
      }
    >
      <JobModeOutput
        kind="batch_scrape"
        starting={submit.isPending ? "Starting the batch" : null}
        problem={problem}
        jobId={jobId}
        withMetadata={form.options.metadataInJson}
      />
    </PlaygroundLayout>
  );
}
