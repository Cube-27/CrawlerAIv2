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

/** Each row's title, by its prompt's name prefix (`call-scrape`, `integrate-scrape`). */
const TITLES: Readonly<Record<string, string>> = {
  call: "Use it with coding agents",
  integrate: "Build on top of it",
};

/** A mode's file: two sections, each a level-1 heading naming the prompt (CommonMark §4.2 ATX headings) and its text.
 * Splitting at the headings with a capture group yields the text before the first one, then name and text in turn. */
function parse(file: string): AgentPrompt[] {
  const [, ...parts] = file.split(/^# (.+)$/m);
  const prompts: AgentPrompt[] = [];
  for (let i = 0; i + 1 < parts.length; i += 2) {
    const name = parts[i] ?? "";
    const prefix = name.slice(0, name.indexOf("-"));
    prompts.push({ title: TITLES[prefix] ?? name, name, text: (parts[i + 1] ?? "").trim() });
  }
  return prompts;
}

/** Every mode's prompts, parsed once from its Markdown file under `prompts/`. */
const PROMPTS: Readonly<Record<ModeId, readonly AgentPrompt[]>> = {
  scrape: parse(scrape),
  batch: parse(batch),
  crawl: parse(crawl),
  map: parse(map),
  extract: parse(extract),
};

/** The prompts of `mode`. */
export function agentPrompts(mode: ModeId): readonly AgentPrompt[] {
  return PROMPTS[mode];
}
