import { Button } from "@heroui/react";
import { useSearchParams } from "react-router";
import { useSubmitCrawl } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { OutputArea } from "../OutputArea";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JOB } from "../run/jobParam";
import { JobRunOutput } from "../run/JobRun";
import { requestUrl, UrlInput } from "../UrlInput";
import { usePageForm } from "../usePageForm";
import { CrawlOptions } from "./CrawlOptions";
import { buildCrawl, crawlErrors, DEFAULT_CRAWL_OPTIONS, INITIAL_CRAWL } from "./form";

/** The Crawl playground at `/crawl` (SPEC-14 §4.2): a start URL, the formats and schema of every page it extracts
 * (`POST /v1/crawl`), its scope and rules in the options, and the run on the page as Batch's results table. */
export function CrawlPlayground() {
  const [params, setParams] = useSearchParams();
  const jobId = params.get(JOB);
  const submit = useSubmitCrawl();
  const problem = problemOf(submit.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_CRAWL,
    problem,
    crawlErrors,
  );

  const start = () => {
    const request = check() ? buildCrawl({ ...form, url: requestUrl(form.url) }) : null;
    if (request === null) return;
    submit.mutate(request, {
      onSuccess: (id) => {
        setParams({ [JOB]: id });
      },
    });
  };

  let output = null;
  if (submit.isPending)
    output = <OutputArea state={{ kind: "pending", label: "Starting the crawl" }} />;
  else if (problem !== null) output = <OutputArea state={{ kind: "failed", problem }} />;
  else if (jobId !== null)
    output = <JobRunOutput key={jobId} jobId={jobId} withMetadata={form.options.metadataInJson} />;

  return (
    <PlaygroundLayout
      mode="crawl"
      validationErrors={validationErrors}
      onSubmit={start}
      input={
        <UrlInput
          value={form.url}
          onChange={(url) => {
            setForm({ ...form, url });
          }}
        />
      }
      tools={
        <PageTools
          form={form}
          defaults={DEFAULT_CRAWL_OPTIONS}
          formatsUnused={form.schemaId !== ""}
          optionsOpen={optionsOpen}
          onOptionsOpen={setOptionsOpen}
          onChange={setForm}
        />
      }
      action={
        <Button type="submit" isPending={submit.isPending}>
          Start crawl
        </Button>
      }
      options={
        optionsOpen ? (
          <CrawlOptions
            options={form.options}
            schemaPageKind={form.schemaId === "" ? null : form.schemaPageKind}
            rulesError={validationErrors["page_kind_rules"]}
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
