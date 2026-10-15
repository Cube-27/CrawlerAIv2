import { Button, FieldError, Form, InputGroup, TextField } from "@heroui/react";
import { useMemo, useState } from "react";
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

/** RFC 3986 §3.1: a URI starts with its scheme and `:`. The bar shows `https://`, so text typed without a scheme
 * gets it. */
const HAS_SCHEME = /^[a-z][a-z\d+.-]*:/i;

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
  const [noFormat, setNoFormat] = useState(false);
  const validationErrors = useMemo(() => {
    const errors = state.kind === "failed" ? fieldErrors(state.problem) : NO_ERRORS;
    return noFormat ? { ...errors, formats: NO_FORMAT } : errors;
  }, [state, noFormat]);

  const submit = () => {
    if (asksForNothing(form)) {
      setNoFormat(true);
      return;
    }
    setNoFormat(false);
    const request = buildRequest({ ...form, url: requestUrl(form.url) });
    // A schema's records need a page kind, which is set in the options panel.
    if (request === null) {
      setOptionsOpen(true);
      return;
    }
    setState({ kind: "pending" });
    void runScrape(client, request).then(setState);
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
