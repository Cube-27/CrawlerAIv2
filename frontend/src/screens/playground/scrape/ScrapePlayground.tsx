import { Button } from "@heroui/react";
import { useMemo, useRef, useState } from "react";
import { fieldErrors } from "../../../api/problem";
import { useApiClient } from "../../../app/auth";
import { SchemaSelect } from "../../../components/SchemaSelect";
import { FormatSelect } from "../FormatSelect";
import { OptionsToggle } from "../OptionsPanel";
import { OutputArea, type OutputState } from "../OutputArea";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { requestUrl, UrlInput } from "../UrlInput";
import {
  asksForNothing,
  buildRequest,
  requestPageKind,
  INITIAL_FORM,
  optionsChanged,
  withSchema,
  type ScrapeFormState,
} from "./form";
import { runScrape, type ScrapeRun } from "./run";
import { ScrapeOptions } from "./ScrapeOptions";
import { ScrapeResult } from "./ScrapeResult";

type ScrapeState = { kind: "idle" } | { kind: "pending" } | ScrapeRun;

const NO_ERRORS: Readonly<Record<string, string>> = {};

const NO_FORMAT = { formats: "Choose a format, Metadata in JSON or a schema." };
const NO_SCHEMA_PAGE_KIND = { page_kind: "The schema names no page kind, which its records need." };
const NO_LISTING_RECORDS = { page_kind: "Records of listing pages are not available yet." };

/** Why `form` can't be sent, by field: it asks for no format, or its schema's records are for no page kind it can ask
 * for (its page kind is none, or one the server refuses records of). Derived from the current form, so a change
 * anywhere that fixes it clears it; each answer is one constant, so the errors change only when the reason does. */
function clientErrorsOf(form: ScrapeFormState): Readonly<Record<string, string>> {
  if (asksForNothing(form)) return NO_FORMAT;
  if (form.schemaId === "" || requestPageKind(form) !== null) return NO_ERRORS;
  return form.schemaPageKind === null ? NO_SCHEMA_PAGE_KIND : NO_LISTING_RECORDS;
}

function outputState(state: Exclude<ScrapeState, { kind: "idle" }>): OutputState {
  if (state.kind === "pending") return { kind: "pending", label: "Scraping" };
  if (state.kind === "failed") return state;
  return {
    kind: "done",
    content: <ScrapeResult response={state.response} fieldTypes={state.fieldTypes} />,
  };
}

/** The Scrape playground at `/` (SPEC-14 §4.2): the mode switch, the command bar with `POST /v1/scrape`'s URL, format
 * and schema, the inline options panel, then what the scrape returned. */
export function ScrapePlayground() {
  const client = useApiClient();
  const [form, setForm] = useState<ScrapeFormState>(INITIAL_FORM);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });
  const [refused, setRefused] = useState(false);
  // Only the latest scrape's reply is shown; an earlier one still in flight is dropped.
  const latest = useRef(0);
  const clientErrors = refused ? clientErrorsOf(form) : NO_ERRORS;
  const validationErrors = useMemo(
    () => ({
      ...(state.kind === "failed" ? fieldErrors(state.problem) : NO_ERRORS),
      ...clientErrors,
    }),
    [state, clientErrors],
  );

  const submit = () => {
    const request = buildRequest({ ...form, url: requestUrl(form.url) });
    setRefused(request === null);
    if (request === null) {
      if (!asksForNothing(form)) setOptionsOpen(true);
      return;
    }
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
        <>
          <OptionsToggle
            isOpen={optionsOpen}
            changed={optionsChanged(form.options)}
            onChange={setOptionsOpen}
          />
          <FormatSelect
            value={form.formats}
            onChange={(formats) => {
              setForm({ ...form, formats });
            }}
          />
          <SchemaSelect
            value={form.schemaId}
            noneLabel="No schema"
            hideLabel
            onChange={(schemaId, schema) => {
              setForm(withSchema(form, schemaId, schema?.page_kind ?? null));
            }}
          />
        </>
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
      {state.kind === "idle" ? null : <OutputArea state={outputState(state)} />}
    </PlaygroundLayout>
  );
}
