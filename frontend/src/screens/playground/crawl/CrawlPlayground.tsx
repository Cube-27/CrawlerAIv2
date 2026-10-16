import { Button } from "@heroui/react";
import { useSubmitCrawl } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import type { CrawlRequest } from "../../../api/jobs";
import { useFieldsReview } from "../fields/useFieldsReview";
import { optionsChanged } from "../pageRequest";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobModeOutput } from "../run/JobRun";
import { useShownJob } from "../run/useShownJob";
import { requestUrl, UrlInput } from "../UrlInput";
import { usePageForm } from "../usePageForm";
import { CrawlOptions } from "./CrawlOptions";
import {
  buildCrawl,
  crawlErrors,
  crawlForm,
  DEFAULT_CRAWL_OPTIONS,
  INITIAL_CRAWL,
  rulesPageKind,
} from "./form";

/** The Crawl playground at `/crawl` (SPEC-14 §4.2): a start URL, the formats and schema of every page it extracts
 * (`POST /v1/crawl`), its scope and rules in the options, and the run on the page (`?job=`) as Batch's results table;
 * before any run, the recent crawls. */
export function CrawlPlayground() {
  const submit = useSubmitCrawl();
  const problem = problemOf(submit.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_CRAWL,
    problem,
    crawlErrors,
  );
  const { jobId, onEdit, show } = useShownJob(crawlForm, setForm);

  const request = buildCrawl({ ...form, url: requestUrl(form.url) });
  const review = useFieldsReview((sent: CrawlRequest) => {
    submit.mutate(sent, { onSuccess: show });
  });
  const start = () => {
    if (!check() || request === null) return;
    review.start(request, rulesPageKind(form.options.rules));
  };

  return (
    <PlaygroundLayout
      mode="crawl"
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
      optionsChanged={optionsChanged(form.options, DEFAULT_CRAWL_OPTIONS)}
      tools={<PageTools form={form} formatsUnused={form.schemaId !== ""} onChange={setForm} />}
      action={
        <Button type="submit" isPending={submit.isPending}>
          Start crawl
        </Button>
      }
      options={
        <CrawlOptions
          options={form.options}
          schemaPageKind={form.schemaId === "" ? null : form.schemaPageKind}
          rulesError={validationErrors["page_kind_rules"]}
          onChange={(options) => {
            setForm({ ...form, options });
          }}
        />
      }
    >
      <JobModeOutput
        kind="crawl"
        starting={submit.isPending ? "Starting the crawl" : null}
        problem={problem}
        jobId={jobId}
        withMetadata={form.options.metadataInJson}
      />
      {review.drawer}
    </PlaygroundLayout>
  );
}
