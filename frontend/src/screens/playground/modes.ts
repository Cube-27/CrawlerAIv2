import { BranchesDown, Funnel, GraphNode, ListCheck, Magnifier } from "@gravity-ui/icons";
import type { ComponentType, SVGProps } from "react";
import type { JobKind } from "../../api/jobs";
import { JOB } from "./run/jobParam";

/** The playground's modes (SPEC-14 §4.2, §4.8): each has its own route, so the mode is in the URL. This is the one
 * list of modes: the mode switch, the sidebar and the job links all read it. */
export type ModeId = "scrape" | "batch" | "extract" | "map" | "crawl";

export interface Mode {
  id: ModeId;
  label: string;
  href: string;
  /** The kind of the jobs it runs (SPEC-01 §4.2). */
  kind: JobKind;
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

/** The modes in the sidebar's order (SPEC-14 §4.8). */
export const MODES: readonly Mode[] = [SCRAPE, BATCH, CRAWL, MAP, EXTRACT];

/** The modes under the mode switch's captions (SPEC-14 §4.2). */
export const MODE_GROUPS: readonly ModeGroup[] = [
  { caption: "Pages", modes: [SCRAPE, BATCH, EXTRACT] },
  { caption: "Sites", modes: [MAP, CRAWL] },
];

export function modeOf(id: ModeId): Mode {
  const mode = MODES.find((entry) => entry.id === id);
  if (mode === undefined) throw new Error(`no mode ${id}`);
  return mode;
}

/** Where a job of `kind` opens (SPEC-14 §4.8): its mode's route with `?job=`; null for a kind no mode runs (`learn`),
 * which keeps its job page. */
export function runPath(kind: JobKind, id: string): string | null {
  const mode = MODES.find((entry) => entry.kind === kind);
  return mode === undefined
    ? null
    : `${mode.href}?${new URLSearchParams({ [JOB]: id }).toString()}`;
}
