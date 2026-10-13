import { Alert } from "@heroui/react";
import { useState } from "react";
import { useApiClient } from "../../app/auth";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { buildRequest, INITIAL_FORM, type ScrapeFormState } from "./form";
import { runScrape, type ScrapeRun } from "./run";
import { ScrapeForm } from "./ScrapeForm";
import { ScrapeResult } from "./ScrapeResult";

type ScrapeState = { kind: "idle" } | { kind: "pending" } | ScrapeRun;

// RFC 9110 §10.2.3: Retry-After is delay-seconds (digits only) or an HTTP date.
function retryText(retryAfter: string): string {
  return /^\d+$/.test(retryAfter)
    ? `Retry after ${retryAfter} seconds.`
    : `Retry after ${retryAfter}.`;
}

function Failure({ run }: Readonly<{ run: Extract<ScrapeRun, { kind: "failed" }> }>) {
  return (
    <ProblemAlert problem={run.problem}>
      {run.problem.errors.map((error) => (
        <Alert.Description key={`${error.field}:${error.reason}`}>
          {error.field}: {error.reason}
        </Alert.Description>
      ))}
      {run.retryAfter === null ? null : (
        <Alert.Description>{retryText(run.retryAfter)}</Alert.Description>
      )}
    </ProblemAlert>
  );
}

function serverErrors(state: ScrapeState): Readonly<Record<string, string>> {
  if (state.kind !== "failed") return {};
  return Object.fromEntries(state.problem.errors.map(({ field, reason }) => [field, reason]));
}

/** The form for `POST /v1/scrape` and what it returned (SPEC-12 §4.3). */
export function ScrapeScreen() {
  const client = useApiClient();
  const [form, setForm] = useState<ScrapeFormState>(INITIAL_FORM);
  const [state, setState] = useState<ScrapeState>({ kind: "idle" });

  const submit = () => {
    const request = buildRequest(form);
    if (request === null) return;
    setState({ kind: "pending" });
    void runScrape(client, request).then(setState);
  };

  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Scrape" />
      {state.kind === "failed" ? <Failure run={state} /> : null}
      <ScrapeForm
        form={form}
        isPending={state.kind === "pending"}
        serverErrors={serverErrors(state)}
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
