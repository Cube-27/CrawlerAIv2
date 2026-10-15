import { Label, Table, TextArea, TextField } from "@heroui/react";
import type { FetchAttempt, PageMetadata, ScrapeResponse } from "../../../api/scrape";

/** A text format (markdown, html, raw_html) in a read-only text area, to read, scroll and copy as sent. */
export function TextFormat({ label, text }: Readonly<{ label: string; text: string }>) {
  return (
    <TextField isReadOnly value={text}>
      <Label>{label}</Label>
      <TextArea rows={20} />
    </TextField>
  );
}

/** Pairs of a name and the value the server sent, in a two-column table. */
export function NameValueTable({
  label,
  rows,
}: Readonly<{ label: string; rows: readonly (readonly [string, string])[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label={label}>
          <Table.Header>
            <Table.Column isRowHeader>Name</Table.Column>
            <Table.Column>Value</Table.Column>
          </Table.Header>
          <Table.Body items={rows.map(([name, value]) => ({ id: name, name, value }))}>
            {(row) => (
              <Table.Row id={row.id}>
                <Table.Cell>{row.name}</Table.Cell>
                <Table.Cell>{row.value}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

/** The page's links (SPEC-07 §4.5), as text: they lead to other sites and are not followed from here. */
export function LinksTable({ links }: Readonly<{ links: readonly string[] }>) {
  return (
    <Table>
      <Table.ScrollContainer>
        <Table.Content aria-label="Links">
          <Table.Header>
            <Table.Column isRowHeader>URL</Table.Column>
          </Table.Header>
          <Table.Body items={links.map((url) => ({ id: url }))}>
            {(link) => (
              <Table.Row id={link.id}>
                <Table.Cell>{link.id}</Table.Cell>
              </Table.Row>
            )}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}

function text(value: string | null): string {
  return value ?? "—";
}

export function MetadataTable({ metadata }: Readonly<{ metadata: PageMetadata }>) {
  return (
    <NameValueTable
      label="Metadata"
      rows={[
        ["Title", text(metadata.title)],
        ["Description", text(metadata.description)],
        ["Language", text(metadata.language)],
        ["Canonical", text(metadata.canonical)],
        ["Structured data types", metadata.structured_data_types.join(", ") || "—"],
        ...Object.entries(metadata.og),
      ]}
    />
  );
}

export function FetchView({ fetch }: Readonly<{ fetch: NonNullable<ScrapeResponse["fetch"]> }>) {
  const attempts: (FetchAttempt & { id: number })[] = fetch.attempts.map((attempt, id) => ({
    ...attempt,
    id,
  }));
  return (
    <div className="flex flex-col gap-4">
      <NameValueTable
        label="Fetch"
        rows={[
          ["Method", fetch.method],
          ["HTTP status", fetch.status_code === null ? "—" : String(fetch.status_code)],
          ["Block class", fetch.block_class],
        ]}
      />
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Fetch attempts">
            <Table.Header>
              <Table.Column isRowHeader>Method</Table.Column>
              <Table.Column>HTTP status</Table.Column>
              <Table.Column>Block class</Table.Column>
              <Table.Column>Duration (ms)</Table.Column>
              <Table.Column>Error</Table.Column>
            </Table.Header>
            <Table.Body items={attempts}>
              {(attempt) => (
                <Table.Row id={attempt.id}>
                  <Table.Cell>{attempt.method}</Table.Cell>
                  <Table.Cell>{attempt.status === null ? "—" : String(attempt.status)}</Table.Cell>
                  <Table.Cell>{attempt.block_class}</Table.Cell>
                  <Table.Cell>{String(attempt.duration_ms)}</Table.Cell>
                  <Table.Cell>{attempt.error ?? "—"}</Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </div>
  );
}

export function UsageTable({ usage }: Readonly<{ usage: ScrapeResponse["usage"] }>) {
  return (
    <NameValueTable
      label="Usage"
      rows={[
        ["LLM calls", String(usage.llm_calls)],
        ["LLM tokens in", String(usage.llm_tokens_in)],
        ["LLM tokens out", String(usage.llm_tokens_out)],
        ["Browser seconds", String(usage.browser_seconds)],
        ["HTTP requests", String(usage.http_requests)],
      ]}
    />
  );
}
