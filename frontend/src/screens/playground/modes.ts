import { BranchesDown, GraphNode, ListCheck, Magnifier } from "@gravity-ui/icons";
import type { ComponentType, SVGProps } from "react";

/** The playground's modes (SPEC-14 §4.2, §4.8): each has its own route, so the mode is in the URL. This is the one
 * list of modes: the mode switch and the sidebar both show it. A mode is listed once its PR builds it; Extract follows
 * in SPEC-14 PR 7. */
export type ModeId = "scrape" | "batch" | "map" | "crawl";

export interface Mode {
  id: ModeId;
  label: string;
  href: string;
  /** The sidebar entry's icon. */
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

export interface ModeGroup {
  /** The caption over the group's tabs. */
  caption: string;
  modes: readonly Mode[];
}

const SCRAPE: Mode = { id: "scrape", label: "Scrape", href: "/", icon: Magnifier };

const BATCH: Mode = { id: "batch", label: "Batch", href: "/batch", icon: ListCheck };

const MAP: Mode = { id: "map", label: "Map", href: "/map", icon: BranchesDown };

const CRAWL: Mode = { id: "crawl", label: "Crawl", href: "/crawl", icon: GraphNode };

/** The modes in the sidebar's order (SPEC-14 §4.8). */
export const MODES: readonly Mode[] = [SCRAPE, BATCH, CRAWL, MAP];

/** The modes under the mode switch's captions (SPEC-14 §4.2). */
export const MODE_GROUPS: readonly ModeGroup[] = [
  { caption: "Pages", modes: [SCRAPE, BATCH] },
  { caption: "Sites", modes: [MAP, CRAWL] },
];
