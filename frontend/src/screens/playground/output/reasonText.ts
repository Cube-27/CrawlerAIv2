/** Why a scrape that reached its page answered no rows: structured data, the config, the page's calls, its state and its repeated item blocks gave none, so the
 * row reader (role C), which fills the rows of blocks, had none to read. */
const NO_ROWS = "no_rows: no_blocks";

const NO_ROWS_SENTENCE =
  "No rows: no source stated any, and the page shows no repeated items for the row reader.";

/** A scrape's `reason` as a sentence, or null when it is another reason (a code the screen shows as it is). The reason
 * itself is the sentence's tooltip, as the server wrote it. */
export function reasonSentence(reason: string): string | null {
  return reason === NO_ROWS ? NO_ROWS_SENTENCE : null;
}
