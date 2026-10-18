/** Why a scrape that reached its page answered no rows (rest-api spec, "Scrape outcomes, not errors, for page
 * failures"): structured data, the config, the page's calls and its repeated item blocks gave none, so the row reader
 * (role C), which fills the rows of blocks, was not asked. */
const NO_ROWS = "no_rows: not_asked";

const NO_ROWS_SENTENCE =
  "No rows: structured data, the config, the page's calls and its repeated items gave none, so the row reader was not asked.";

/** A scrape's `reason` as a sentence, or null when it is another reason (a code the screen shows as it is). The reason
 * itself is the sentence's tooltip, as the server wrote it. */
export function reasonSentence(reason: string): string | null {
  return reason === NO_ROWS ? NO_ROWS_SENTENCE : null;
}
