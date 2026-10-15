/** The playground's modes (SPEC-14 §4.2, §4.8): each has its own route, so the mode is in the URL. A mode is listed
 * once its PR builds it; Batch, Crawl, Map and Extract follow in SPEC-14 PRs 4, 6 and 7. */
export type ModeId = "scrape";

export interface Mode {
  id: ModeId;
  label: string;
  href: string;
}

export interface ModeGroup {
  /** The caption over the group's tabs. */
  caption: string;
  modes: readonly Mode[];
}

export const SCRAPE: Mode = { id: "scrape", label: "Scrape", href: "/" };

export const MODE_GROUPS: readonly ModeGroup[] = [{ caption: "Pages", modes: [SCRAPE] }];
