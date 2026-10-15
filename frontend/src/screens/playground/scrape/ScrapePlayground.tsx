import { Button, FieldError, Form, InputGroup, TextField } from "@heroui/react";
import { useMemo, useRef, useState } from "react";
import { fieldErrors } from "../../../api/problem";
import { useApiClient } from "../../../app/auth";
import { LoadingView } from "../../../components/LoadingView";
import { PageHeader } from "../../../components/PageHeader";
import { ProblemAlert } from "../../../components/ProblemAlert";
import { SchemaSelect } from "../../../components/SchemaSelect";
import { CommandBar } from "../CommandBar";
import { FormatSelect } from "../FormatSelect";
import { ModeSwitch } from "../ModeSwitch";
import { OptionsToggle } from "../OptionsPanel";
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

const NO_FORMAT = "Choose a format, Metadata in JSON or a schema.";

/** Why the chosen schema's records can't be asked for: its page kind is none, or one the server refuses records of. */
function noPageKind(form: ScrapeFormState): string {
  return form.schemaPageKind === null
    ? "The schema names no page kind, which its records need."
    : "Records of listing pages are not available yet.";
}

/** RFC 3986 §3: a URL with an authority starts with its scheme and `://`. The bar shows `https://`, so text typed
 * without one gets it; `host:port` (RFC 3986 §3.2) has no `//`, so it is a host, not a scheme. */
const HAS_SCHEME = /^[a-z][a-z\d+.-]*:\/\//i;

function requestUrl(text: string): string {
  const url = text.trim();
  return url === "" || HAS_SCHEME.test(url) ? url : `https://${url}`;
}

function UrlInput({
  form,
  onChange,
}: Readonly<{ form: ScrapeFormState; onChange: (form: ScrapeFormState) => void }>) {
  return (
    <TextField
      aria-label="URL"
      isRequired
      name="url"
      value={form.url}
      onChange={(url) => {
        onChange({ ...form, url });
      }}
    >
      <InputGroup fullWidth>
        <InputGroup.Prefix>https://</InputGroup.Prefix>
        <InputGroup.Input autoComplete="off" inputMode="url" placeholder="example.com" />
      </InputGroup>
      <FieldError />
    </TextField>
  );
}

/** The Scrape playground at `/` (SPEC-14 §4.2): the mode switch, the command bar with `POST /v1/scrape`'s URL, format
 * and schema, the inline options panel, then what the scrape returned. */
export function ScrapePlayground() {
  const client = useApiClient();
  const [form, setForm] = useState<ScrapeFormState>(INITIAL_FORM);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });
  const [clientErrors, setClientErrors] = useState<Readonly<Record<string, string>>>(NO_ERRORS);
  // Only the latest scrape's reply is shown; an earlier one still in flight is dropped.
  const latest = useRef(0);
  const validationErrors = useMemo(
    () => ({
      ...(state.kind === "failed" ? fieldErrors(state.problem) : NO_ERRORS),
      ...clientErrors,
    }),
    [state, clientErrors],
  );

  const submit = () => {
    const request = buildRequest({ ...form, url: requestUrl(form.url) });
    if (request === null) {
      if (asksForNothing(form)) {
        setClientErrors({ formats: NO_FORMAT });
      } else {
        setClientErrors({ page_kind: noPageKind(form) });
        setOptionsOpen(true);
      }
      return;
    }
    setClientErrors(NO_ERRORS);
    const run = ++latest.current;
    setState({ kind: "pending" });
    void runScrape(client, request).then((result) => {
      if (run === latest.current) setState(result);
    });
  };

  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Playground" />
      <ModeSwitch current="scrape" />
      <Form
        className="flex flex-col gap-4"
        validationErrors={validationErrors}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <CommandBar
          input={<UrlInput form={form} onChange={setForm} />}
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
        />
        {optionsOpen ? (
          <ScrapeOptions
            options={form.options}
            hasSchema={form.schemaId !== ""}
            schemaPageKind={requestPageKind(form)}
            onChange={(options) => {
              setForm({ ...form, options });
            }}
          />
        ) : null}
      </Form>
      {state.kind === "failed" ? <ProblemAlert problem={state.problem} /> : null}
      {state.kind === "pending" ? <LoadingView label="Scraping" /> : null}
      {state.kind === "done" ? (
        <ScrapeResult response={state.response} fieldTypes={state.fieldTypes} />
      ) : null}
    </section>
  );
}
