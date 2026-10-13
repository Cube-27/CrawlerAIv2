import { Tabs, Typography } from "@heroui/react";
import { memo, type ReactNode } from "react";
import type { ScrapeResponse } from "../../api/scrape";
import { OutcomeLabel } from "../../components/OutcomeLabel";
import {
  DraftSchemaView,
  FetchView,
  LinksTable,
  MetadataTable,
  TextFormat,
  UsageTable,
} from "./FormatViews";
import { RecordsView } from "./RecordsView";
import type { FieldTypes } from "./run";

interface ResultTab {
  id: string;
  label: string;
  content: ReactNode;
}

/** A tab per member the response carries: the requested formats, then the draft schema, fetch and usage. */
function resultTabs(response: ScrapeResponse, fieldTypes: FieldTypes): ResultTab[] {
  const tabs: (ResultTab | null)[] = [
    response.records === undefined
      ? null
      : {
          id: "records",
          label: "Records",
          content: <RecordsView records={response.records} fieldTypes={fieldTypes} />,
        },
    response.markdown === undefined
      ? null
      : {
          id: "markdown",
          label: "Markdown",
          content: <TextFormat label="Markdown" text={response.markdown} />,
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
    response.schema === undefined
      ? null
      : {
          id: "schema",
          label: "Draft schema",
          content: <DraftSchemaView schema={response.schema} />,
        },
    { id: "fetch", label: "Fetch", content: <FetchView fetch={response.fetch} /> },
    { id: "usage", label: "Usage", content: <UsageTable usage={response.usage} /> },
  ];
  return tabs.filter((tab) => tab !== null);
}

/** What one scrape returned: its outcome and final URL, then a tab per returned member. Memoized: the form above
 * re-renders on every keystroke, and a result can hold megabytes of page text. */
export const ScrapeResult = memo(function ScrapeResult({
  response,
  fieldTypes,
}: Readonly<{ response: ScrapeResponse; fieldTypes: FieldTypes }>) {
  const tabs = resultTabs(response, fieldTypes);
  return (
    <section aria-label="Result" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={2}>Result</Typography.Heading>
        <OutcomeLabel outcome={response.outcome} />
        <Typography.Code>{response.final_url}</Typography.Code>
        <Typography.Paragraph size="sm" color="muted">
          Fetched {response.fetched_at}
        </Typography.Paragraph>
      </div>
      <Tabs>
        <Tabs.ListContainer>
          <Tabs.List aria-label="Scrape result">
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
    </section>
  );
});
