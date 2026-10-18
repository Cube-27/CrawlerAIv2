import { BranchesDown, Funnel, GraphNode, ListCheck, Magnifier, Globe } from "@gravity-ui/icons";
import type { ComponentType, SVGProps } from "react";
import type { JobKind } from "../../api/jobs";
import { JOB } from "./run/jobParam";

/** The playground's modes (frontend spec): each has its own route, so the mode is in the URL. This is the one
 * list of modes: the mode switch, the sidebar and the job links all read it. */
export type ModeId = "scrape" | "batch" | "extract" | "map" | "crawl" | "search";

export interface Mode {
  id: ModeId;
  label: string;
  href: string;
  /** The kind of the jobs it runs (persistence-storage spec); null for a mode that runs none (Search answers at once). */
  kind: JobKind | null;
  /** The sidebar entry's icon. */
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export interface ModeGroup {
  /** The caption over the group's tabs. */
  caption: string;
  modes: readonly Mode[];
}

const SCRAPE: Mode = { id: "scrape", label: "Scrape", href: "/", kind: "scrape", icon: Magnifier };

const BATCH: Mode = {
  id: "batch",
  label: "Batch",
  href: "/batch",
  kind: "batch_scrape",
  icon: ListCheck,
};

const EXTRACT: Mode = {
  id: "extract",
  label: "Extract",
  href: "/extract",
  kind: "extract",
  icon: Funnel,
};

const MAP: Mode = { id: "map", label: "Map", href: "/map", kind: "map", icon: BranchesDown };

const CRAWL: Mode = { id: "crawl", label: "Crawl", href: "/crawl", kind: "crawl", icon: GraphNode };

const SEARCH: Mode = { id: "search", label: "Search", href: "/search", kind: null, icon: Globe };

/** The modes under the mode switch's captions (frontend spec); the sidebar lists them in this order too (D-0834). */
export const MODE_GROUPS: readonly ModeGroup[] = [
  { caption: "Pages", modes: [SCRAPE, BATCH, EXTRACT] },
  { caption: "Sites", modes: [MAP, CRAWL] },
  { caption: "Web", modes: [SEARCH] },
];

export const MODES: readonly Mode[] = MODE_GROUPS.flatMap((group) => group.modes);

/** Where a job of `kind` opens (frontend spec): its mode's route with `?job=`; null for a kind no mode runs (`learn`),
 * which keeps its job page. */
export function runPath(kind: JobKind, id: string): string | null {
  const mode = MODES.find((entry) => entry.kind === kind);
  return mode === undefined
    ? null
    : `${mode.href}?${new URLSearchParams({ [JOB]: id }).toString()}`;
}
