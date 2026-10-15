import type { ModeId } from "../modes";
import batch from "../prompts/batch.md?raw";
import crawl from "../prompts/crawl.md?raw";
import extract from "../prompts/extract.md?raw";
import map from "../prompts/map.md?raw";
import scrape from "../prompts/scrape.md?raw";

/** One prompt for coding agents (SPEC-14 §4.7). */
export interface AgentPrompt {
  title: string;
  /** The prompt's short name: its heading in the mode's file. */
  name: string;
  /** The text copied: the section under the heading. */
  text: string;
}

const FILES: Readonly<Record<ModeId, string>> = { scrape, batch, crawl, map, extract };

/** The two rows in order, one per level-1 heading of a mode's file (CommonMark §4.2 ATX headings). */
const TITLES = ["Use it with coding agents", "Build on top of it"] as const;

const HEADING = /^# (.+)$/m;

/** The sections of `text`, each a level-1 heading and the lines up to the next one. */
function sections(text: string): { name: string; text: string }[] {
  return text
    .split(/^(?=# )/m)
    .map((section) => {
      const name = HEADING.exec(section)?.[1] ?? "";
      return { name, text: section.replace(HEADING, "").trim() };
    })
    .filter((section) => section.name !== "");
}

/** The prompts of `mode`, from its Markdown file under `prompts/`. */
export function agentPrompts(mode: ModeId): AgentPrompt[] {
  return sections(FILES[mode]).map((section, i) => ({
    title: TITLES[i] ?? section.name,
    ...section,
  }));
}
