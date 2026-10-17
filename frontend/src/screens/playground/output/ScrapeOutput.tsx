import { Tabs, Typography } from "@heroui/react";
import { memo, useMemo, type ReactNode } from "react";
import type { FieldTypes } from "../../../api/field";
import type { ScrapeResponse } from "../../../api/scrape";
import { EmptyView } from "../../../components/EmptyView";
import { JsonView } from "../../../components/JsonView";
import { OutcomeLabel } from "../../../components/OutcomeLabel";
import { RecordList } from "../../../components/RecordFields";
import { Timestamp } from "../../../components/Timestamp";
import { hasUncalibrated, UncalibratedBadge } from "../../../components/UncalibratedBadge";
import { scrapeJson } from "./cleanJson";
import {
  ArtifactViews,
  ChunksView,
  FetchView,
  LinksTable,
  MetadataTable,
  TextFormat,
  UsageTable,
} from "./FormatViews";

interface OutputTab {
  id: string;
  label: string;
  content: ReactNode;
}

/** The page's clean JSON (SPEC-14 §4.4), with one "uncalibrated" badge above it when a published field is. */
function JsonTab({
  response,
  fieldTypes,
  withMetadata,
}: Readonly<{ response: ScrapeResponse; fieldTypes: FieldTypes; withMetadata: boolean }>) {
  // One value per response: JsonView keeps its text and tokens while the value is the same object.
  const item = useMemo(
    () => scrapeJson(response, fieldTypes, withMetadata),
    [response, fieldTypes, withMetadata],
  );
  return (
    <div className="flex flex-col gap-3">
      {hasUncalibrated(response.records ?? []) ? (
        <div>
          <UncalibratedBadge records={response.records ?? []} />
        </div>
      ) : null}
      <JsonView label="Page JSON" value={item} filename={`job-${response.job_id}.json`} />
    </div>
  );
}

/** The records with every field attribute (INV-22), or why there are none. */
function TableTab({
  response,
  fieldTypes,
}: Readonly<{ response: ScrapeResponse; fieldTypes: FieldTypes }>) {
  if (response.records === undefined) {
    return (
      <EmptyView title="No records">Choose a schema to extract records from the page.</EmptyView>
    );
  }
  return <RecordList records={response.records} fieldTypes={fieldTypes} />;
}

/** The page formats the response carries, each in its own tab. */
function formatTabs(response: ScrapeResponse): OutputTab[] {
  const tabs: (OutputTab | null)[] = [
    response.markdown === undefined
      ? null
      : {
          id: "markdown",
          label: "Markdown",
          content: <TextFormat label="Markdown" text={response.markdown} />,
        },
    response.markdown_fit === undefined
      ? null
      : {
          id: "markdown_fit",
          label: "Markdown (fit)",
          content: <TextFormat label="Markdown (fit)" text={response.markdown_fit} />,
        },
    response.chunks === undefined
      ? null
      : { id: "chunks", label: "Chunks", content: <ChunksView chunks={response.chunks} /> },
    response.screenshot === undefined && response.pdf === undefined
      ? null
      : {
          id: "capture",
          label: response.screenshot === undefined ? "PDF" : "Screenshot",
          content: <ArtifactViews screenshot={response.screenshot} pdf={response.pdf} />,
        },
    response.html === undefined
      ? null
      : { id: "html", label: "HTML", content: <TextFormat label="HTML" text={response.html} /> },
    response.raw_html === undefined
      ? null
      : {
          id: "raw_html",
          label: "Raw HTML",
          content: <TextFormat label="Raw HTML" text={response.raw_html} />,
        },
    response.links === undefined
      ? null
      : { id: "links", label: "Links", content: <LinksTable links={response.links} /> },
    response.metadata === undefined
      ? null
      : {
          id: "metadata",
          label: "Metadata",
          content: <MetadataTable metadata={response.metadata} />,
        },
  ];
  return tabs.filter((tab) => tab !== null);
}

/** SPEC-14 §4.3: JSON first, then Table, the page formats, and Usage with how the page was fetched. */
function outputTabs(
  response: ScrapeResponse,
  fieldTypes: FieldTypes,
  withMetadata: boolean,
): OutputTab[] {
  return [
    {
      id: "json",
      label: "JSON",
      content: <JsonTab response={response} fieldTypes={fieldTypes} withMetadata={withMetadata} />,
    },
    {
      id: "table",
      label: "Table",
      content: <TableTab response={response} fieldTypes={fieldTypes} />,
    },
    ...formatTabs(response),
    {
      id: "usage",
      label: "Usage",
      content: (
        <div className="flex flex-col gap-4">
          <UsageTable usage={response.usage} />
          {/* No fetch when robots.txt kept the page from being fetched. */}
          {response.fetch === null ? null : <FetchView fetch={response.fetch} />}
        </div>
      ),
    },
  ];
}

/** What one scrape returned: its outcome (with why, for a page robots.txt kept from being fetched) and final URL, then its tabs, JSON first. `withMetadata` (Metadata in JSON)
 * adds the page's metadata to the JSON. Memoized: the form above re-renders on every keystroke, and a result can hold
 * megabytes of page text. */
export const ScrapeOutput = memo(function ScrapeOutput({
  response,
  fieldTypes,
  withMetadata,
}: Readonly<{ response: ScrapeResponse; fieldTypes: FieldTypes; withMetadata: boolean }>) {
  const tabs = outputTabs(response, fieldTypes, withMetadata);
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={2}>Result</Typography.Heading>
        <OutcomeLabel outcome={response.outcome} />
        {response.reason === null ? null : <Typography.Code>{response.reason}</Typography.Code>}
        {response.final_url === null ? null : (
          <Typography.Code>{response.final_url}</Typography.Code>
        )}
        {response.fetched_at === null ? null : (
          <Typography.Paragraph size="sm" color="muted">
            Fetched <Timestamp value={response.fetched_at} />
          </Typography.Paragraph>
        )}
      </div>
      <Tabs>
        <Tabs.ListContainer>
          <Tabs.List aria-label="Scrape output">
            {tabs.map((tab) => (
              <Tabs.Tab key={tab.id} id={tab.id}>
                {tab.label}
                <Tabs.Indicator />
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs.ListContainer>
        {tabs.map((tab) => (
          <Tabs.Panel key={tab.id} id={tab.id}>
            {tab.content}
          </Tabs.Panel>
        ))}
      </Tabs>
    </>
  );
});
