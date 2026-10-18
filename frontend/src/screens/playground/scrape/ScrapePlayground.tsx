import { Button } from "@heroui/react";
import { useRef, useState, type ReactNode } from "react";
import type { ScrapeRequest } from "../../../api/scrape";
import { useApiClient } from "../../../app/auth";
import { useFieldsReview } from "../fields/useFieldsReview";
import { OutputArea, type OutputState } from "../OutputArea";
import { ScrapeOutput } from "../output/ScrapeOutput";
import { optionsChanged, requestFormats, requestPageKind } from "../pageRequest";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobRunOutput } from "../run/JobRun";
import { RecentRuns } from "../run/RecentRuns";
import { useShownJob } from "../run/useShownJob";
import { requestUrl, UrlInput } from "../UrlInput";
import { usePageForm } from "../usePageForm";
import { buildRequest, DEFAULT_OPTIONS, INITIAL_FORM, scrapeErrors, scrapeForm } from "./form";
import { runScrape, type ScrapeRun } from "./run";
import { ScrapeOptions } from "./ScrapeOptions";

type ScrapeState = { kind: "idle" } | { kind: "pending" } | ScrapeRun;

function outputState(
  state: Exclude<ScrapeState, { kind: "idle" }>,
  withMetadata: boolean,
): OutputState {
  if (state.kind === "pending") return { kind: "pending", label: "Scraping" };
  if (state.kind === "failed") return state;
  return {
    kind: "done",
    content: (
      <ScrapeOutput
        response={state.response}
        fieldTypes={state.fieldTypes}
        withMetadata={withMetadata}
      />
    ),
  };
}

/** The Scrape playground at `/` (frontend spec): the mode switch, the command bar with `POST /v1/scrape`'s URL, format
 * and schema, the inline options panel, then what the scrape returned. Field names open their draft for review first
 * (§4.10). Before any scrape, the recent scrapes; one
 * opens as a run (`?job=`, a scrape keeps a job), its page in the results table. */
export function ScrapePlayground() {
  const client = useApiClient();
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_FORM,
    state.kind === "failed" ? state.problem : null,
    scrapeErrors,
  );
  const { jobId, onEdit, clear } = useShownJob(scrapeForm, setForm);
  // Only the latest scrape's reply is shown; an earlier one still in flight is dropped.
  const latest = useRef(0);

  const request = buildRequest({ ...form, url: requestUrl(form.url) });
  const send = (sent: ScrapeRequest) => {
    clear();
    const run = ++latest.current;
    setState({ kind: "pending" });
    void runScrape(client, sent).then((result) => {
      if (run === latest.current) setState(result);
    });
  };
  const review = useFieldsReview(send);
  const submit = () => {
    if (!check() || request === null) return;
    review.start(request);
  };

  const withMetadata = form.options.metadataInJson;
  let output: ReactNode = <RecentRuns kind="scrape" />;
  if (state.kind !== "idle") output = <OutputArea state={outputState(state, withMetadata)} />;
  else if (jobId !== null)
    output = <JobRunOutput key={jobId} jobId={jobId} withMetadata={withMetadata} />;

  return (
    <PlaygroundLayout
      mode="scrape"
      validationErrors={validationErrors}
      onSubmit={submit}
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
      optionsChanged={optionsChanged(form.options, DEFAULT_OPTIONS)}
      tools={<PageTools form={form} onChange={setForm} />}
      action={
        <Button type="submit" isPending={state.kind === "pending"}>
          Scrape
        </Button>
      }
      options={
        <ScrapeOptions
          options={form.options}
          formats={requestFormats(form)}
          hasSchema={form.schemaId !== ""}
          schemaPageKind={requestPageKind(form)}
          onChange={(options) => {
            setForm({ ...form, options });
          }}
        />
      }
    >
      {output}
      {review.drawer}
    </PlaygroundLayout>
  );
}
