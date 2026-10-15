import { Button } from "@heroui/react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useSubmitBatch } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { fieldErrors } from "../../../api/problem";
import { SchemaSelect } from "../../../components/SchemaSelect";
import { FormatSelect } from "../FormatSelect";
import { OptionsToggle } from "../OptionsPanel";
import { OutputArea } from "../OutputArea";
import {
  asksForNothing,
  optionsChanged,
  pageKindErrors,
  requestPageKind,
  withSchema,
} from "../pageRequest";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { JobRunOutput } from "../run/JobRun";
import { BatchOptions } from "./BatchOptions";
import { buildBatch, DEFAULT_BATCH_OPTIONS, INITIAL_BATCH, type BatchFormState } from "./form";
import { UrlList } from "./UrlList";

const NO_ERRORS: Readonly<Record<string, string>> = {};

/** The run the page shows (SPEC-14 §2.4): `?job=<id>`, so a run survives a reload and back goes to the one before. */
const JOB = "job";

/** The Batch playground at `/batch` (SPEC-14 §4.2): a URL list, the same formats, schema and options for every URL
 * (`POST /v1/batch/scrape`), and the run on the same page as a running results table. */
export function BatchPlayground() {
  const [form, setForm] = useState<BatchFormState>(INITIAL_BATCH);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [refused, setRefused] = useState(false);
  const [params, setParams] = useSearchParams();
  const jobId = params.get(JOB);
  const submit = useSubmitBatch();
  const problem = problemOf(submit.error);
  const clientErrors = refused ? pageKindErrors(form) : NO_ERRORS;
  const validationErrors = useMemo(
    () => ({ ...(problem === null ? NO_ERRORS : fieldErrors(problem)), ...clientErrors }),
    [problem, clientErrors],
  );

  const start = () => {
    const request = buildBatch(form);
    setRefused(request === null);
    if (request === null) {
      if (!asksForNothing(form)) setOptionsOpen(true);
      return;
    }
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
        <>
          <OptionsToggle
            isOpen={optionsOpen}
            changed={optionsChanged(form.options, DEFAULT_BATCH_OPTIONS)}
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
