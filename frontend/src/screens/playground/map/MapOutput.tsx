import { Alert, Typography } from "@heroui/react";
import { useState } from "react";
import type { MapResult } from "../../../api/jobs";
import { ScrapeAsBatchBar } from "../run/scrapeAsBatch";
import { LinksTable } from "./LinksTable";

/** What a map found: how many URLs from each source, whether the list was cut short, then the links,
 * whose selected URLs open as a batch. */
export function MapOutput({ result }: Readonly<{ result: MapResult }>) {
  const { urls, sources, truncated } = result;
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  return (
    <>
      <Typography.Paragraph>
        {urls.length} URLs: {sources.sitemap} from sitemaps, {sources.links} from links.
      </Typography.Paragraph>
      {truncated ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The list is cut short.</Alert.Title>
            <Alert.Description>
              More URLs were found than the limit, or reading stopped at a cap or the timeout.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      <ScrapeAsBatchBar selected={selected} />
      <LinksTable urls={urls} selected={selected} onSelect={setSelected} />
    </>
  );
}
