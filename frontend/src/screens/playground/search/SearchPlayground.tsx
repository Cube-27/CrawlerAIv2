import { Button, FieldError, Input, TextField } from "@heroui/react";
import { useSearchWeb } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { OutputArea, type OutputState } from "../OutputArea";
import { optionsChanged } from "../pageRequest";
import { PageTools } from "../PageTools";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { usePageForm } from "../usePageForm";
import { buildSearch, DEFAULT_SEARCH_OPTIONS, INITIAL_SEARCH, searchErrors } from "./form";
import { SearchOptions } from "./SearchOptions";
import { SearchOutput } from "./SearchOutput";

/** The Search playground at `/search`: a query and the result limit (`POST /v1/search`, answered at once),
 * then the results as a list; with Scrape results, the toolbar's Format and Schema say how the batch job it queues
 * scrapes them. A search keeps nothing on the server, so the results stay in the page until the next search. */
export function SearchPlayground() {
  const search = useSearchWeb();
  const problem = problemOf(search.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors, check } = usePageForm(
    INITIAL_SEARCH,
    problem,
    searchErrors,
  );
  const request = buildSearch(form);

  let state: OutputState | null = null;
  if (search.isPending) state = { kind: "pending", label: "Searching the web" };
  else if (problem !== null) state = { kind: "failed", problem };
  else if (search.data !== undefined)
    state = { kind: "done", content: <SearchOutput result={search.data} /> };

  return (
    <PlaygroundLayout
      mode="search"
      validationErrors={validationErrors}
      onSubmit={() => {
        if (check() && request !== null) search.mutate(request);
      }}
      onEdit={null}
      request={request}
      input={
        <TextField
          aria-label="Query"
          name="query"
          value={form.query}
          onChange={(query) => {
            setForm({ ...form, query });
          }}
        >
          <Input autoComplete="off" placeholder="What to search the web for" fullWidth />
          <FieldError />
        </TextField>
      }
      optionsOpen={optionsOpen}
      onOptionsOpen={setOptionsOpen}
      optionsChanged={optionsChanged(form.options, DEFAULT_SEARCH_OPTIONS)}
      tools={
        form.options.scrape ? (
          <PageTools
            form={{ ...form, options: { ...form.options, fields: [] } }}
            formatsUnused={form.schemaId !== ""}
            onChange={(next) => {
              setForm({
                ...form,
                formats: next.formats,
                schemaId: next.schemaId,
                schemaPageKind: next.schemaPageKind,
              });
            }}
          />
        ) : null
      }
      action={
        <Button type="submit" isPending={search.isPending}>
          Search
        </Button>
      }
      options={
        <SearchOptions
          options={form.options}
          onChange={(options) => {
            setForm({ ...form, options });
          }}
        />
      }
    >
      {state === null ? null : <OutputArea state={state} />}
    </PlaygroundLayout>
  );
}
