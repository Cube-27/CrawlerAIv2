import { Button } from "@heroui/react";
import { useRef, useState } from "react";
import { useApiClient } from "../../../app/auth";
import { OutputArea, type OutputState } from "../OutputArea";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { ScrapeOutput } from "../output/ScrapeOutput";
import { requestUrl, UrlInput } from "../UrlInput";
import { pageKindErrors, requestPageKind } from "../pageRequest";
import { PageTools } from "../PageTools";
import { usePageForm } from "../usePageForm";
import { buildRequest, DEFAULT_OPTIONS, INITIAL_FORM } from "./form";
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

/** The Scrape playground at `/` (SPEC-14 §4.2): the mode switch, the command bar with `POST /v1/scrape`'s URL, format
 * and schema, the inline options panel, then what the scrape returned. */
export function ScrapePlayground() {
  const client = useApiClient();
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_FORM,
    state.kind === "failed" ? state.problem : null,
    pageKindErrors,
  );
  // Only the latest scrape's reply is shown; an earlier one still in flight is dropped.
  const latest = useRef(0);

  const submit = () => {
    const request = check() ? buildRequest({ ...form, url: requestUrl(form.url) }) : null;
    if (request === null) return;
    const run = ++latest.current;
    setState({ kind: "pending" });
    void runScrape(client, request).then((result) => {
      if (run === latest.current) setState(result);
    });
  };

  return (
    <PlaygroundLayout
      mode="scrape"
      validationErrors={validationErrors}
      onSubmit={submit}
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
          defaults={DEFAULT_OPTIONS}
          optionsOpen={optionsOpen}
          onOptionsOpen={setOptionsOpen}
          onChange={setForm}
        />
      }
      action={
        <Button type="submit" isPending={state.kind === "pending"}>
          Scrape
        </Button>
      }
      options={
        optionsOpen ? (
          <ScrapeOptions
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
      {state.kind === "idle" ? null : (
        <OutputArea state={outputState(state, form.options.metadataInJson)} />
      )}
    </PlaygroundLayout>
  );
}
