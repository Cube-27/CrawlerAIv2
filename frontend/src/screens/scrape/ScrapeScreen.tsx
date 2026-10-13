import { useMemo, useState } from "react";
import { fieldErrors } from "../../api/problem";
import { useApiClient } from "../../app/auth";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { buildRequest, INITIAL_FORM, type ScrapeFormState } from "./form";
import { runScrape, type ScrapeRun } from "./run";
import { ScrapeForm } from "./ScrapeForm";
import { ScrapeResult } from "./ScrapeResult";

type ScrapeState = { kind: "idle" } | { kind: "pending" } | ScrapeRun;

const NO_ERRORS: Readonly<Record<string, string>> = {};

/** The form for `POST /v1/scrape` and what it returned (SPEC-12 §4.3). */
export function ScrapeScreen() {
  const client = useApiClient();
  const [form, setForm] = useState<ScrapeFormState>(INITIAL_FORM);
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });
  const serverErrors = useMemo(
    () => (state.kind === "failed" ? fieldErrors(state.problem) : NO_ERRORS),
    [state],
  );

  const submit = () => {
    const request = buildRequest(form);
    if (request === null) return;
    setState({ kind: "pending" });
    void runScrape(client, request).then(setState);
  };

  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Scrape" />
      {state.kind === "failed" ? <ProblemAlert problem={state.problem} /> : null}
      <ScrapeForm
        form={form}
        isPending={state.kind === "pending"}
        serverErrors={serverErrors}
        onChange={setForm}
        onSubmit={submit}
      />
      {state.kind === "pending" ? <LoadingView label="Scraping" /> : null}
      {state.kind === "done" ? (
        <ScrapeResult response={state.response} fieldTypes={state.fieldTypes} />
      ) : null}
    </section>
  );
}
