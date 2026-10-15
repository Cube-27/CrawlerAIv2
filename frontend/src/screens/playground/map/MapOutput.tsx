import { Alert, Typography } from "@heroui/react";
import type { MapResult } from "../../../api/jobs";
import { LinksTable } from "./LinksTable";

/** What a map found (SPEC-14 §4.3): how many URLs from each source, whether the list was cut short, then the links. */
export function MapOutput({ result }: Readonly<{ result: MapResult }>) {
  const { urls, sources, truncated } = result;
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
      <LinksTable urls={urls} />
    </>
  );
}
