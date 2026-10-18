/** Why a scrape that reached its page answered no rows, `no_rows: <cause>` (D-1475, `resolve/pipeline.py`): structured
 * data, the config and the page's calls gave none, and the row reader (role C) was not asked, failed, or listed none it
 * could ground. */
const NO_ROWS = "no_rows: ";

const NO_ROWS_CAUSES: Readonly<Record<string, string>> = {
  none_listed:
    "No rows: structured data, the config and the page's calls gave none, and the row reader found none it could ground in the page.",
  not_asked:
    "No rows: structured data, the config and the page's calls gave none, and the row reader was not asked (a schema without row fields, no reader, or a config that reads them).",
};

/** A scrape's `reason` as a sentence, or null when it is another reason (a code the screen shows as it is). The reason
 * itself is the sentence's tooltip, as the server wrote it. */
export function reasonSentence(reason: string): string | null {
  if (!reason.startsWith(NO_ROWS)) return null;
  const cause = reason.slice(NO_ROWS.length);
  return NO_ROWS_CAUSES[cause] ?? `No rows: the row reader failed (${cause}).`;
}
