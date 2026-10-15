import { Button, Checkbox, Table, Typography } from "@heroui/react";
import { ListCheck } from "@gravity-ui/icons";
import type { ComponentProps } from "react";
import { useNavigate } from "react-router";

/** A table's selection as React Aria reports it: every row, or the keys of the selected ones. */
type Selection = Parameters<
  NonNullable<ComponentProps<typeof Table.Content>["onSelectionChange"]>
>[0];

/** Batch from results (SPEC-14 §2.8): URLs selected in a Map or Crawl result open Batch mode with those URLs. They go
 * in the navigation's state, which Batch reads once, as its initial list. */
interface BatchState {
  urls: readonly string[];
}

function isBatchState(state: unknown): state is BatchState {
  if (typeof state !== "object" || state === null || !("urls" in state)) return false;
  const { urls } = state;
  return Array.isArray(urls) && urls.every((url) => typeof url === "string");
}

/** The URL list a navigation's `state` opens Batch with: one URL per line, or "" for none. */
export function batchUrls(state: unknown): string {
  return isBatchState(state) ? state.urls.join("\n") : "";
}

/** Opens Batch mode with `urls`. */
export function useScrapeAsBatch(): (urls: readonly string[]) => void {
  const navigate = useNavigate();
  return (urls) => {
    void navigate("/batch", { state: { urls } satisfies BatchState });
  };
}

/** The URLs selected after the table's selection on one page changes to `selection`: the page's URLs, `pageUrls`,
 * leave and the ones selected there join, so selections on other pages are kept. */
export function selectOnPage(
  selected: ReadonlySet<string>,
  pageUrls: readonly string[],
  selection: Selection,
): Set<string> {
  const kept = [...selected].filter((url) => !pageUrls.includes(url));
  const chosen = selection === "all" ? pageUrls : pageUrls.filter((url) => selection.has(url));
  return new Set([...kept, ...chosen]);
}

/** The table's row checkbox (React Aria's `selection` slot), in a row's first cell or, for the whole page, its
 * column. In a row, React Aria names it by `label` and the row's header ("Select" and the URL). */
export function SelectionCheckbox({ label }: Readonly<{ label: string }>) {
  return (
    <Checkbox aria-label={label} slot="selection">
      <Checkbox.Content>
        <Checkbox.Control>
          <Checkbox.Indicator />
        </Checkbox.Control>
      </Checkbox.Content>
    </Checkbox>
  );
}

/** Above a result table: how many URLs are selected, and "Scrape as batch", which opens Batch mode with them. It keeps
 * its place whatever is selected. */
export function ScrapeAsBatchBar({ selected }: Readonly<{ selected: ReadonlySet<string> }>) {
  const scrapeAsBatch = useScrapeAsBatch();
  return (
    <div className="flex items-center justify-between gap-3">
      <Typography.Paragraph size="sm" color="muted">
        {selected.size} selected
      </Typography.Paragraph>
      <Button
        size="sm"
        variant="secondary"
        isDisabled={selected.size === 0}
        onPress={() => {
          scrapeAsBatch([...selected]);
        }}
      >
        <ListCheck aria-hidden="true" />
        Scrape as batch
      </Button>
    </div>
  );
}
