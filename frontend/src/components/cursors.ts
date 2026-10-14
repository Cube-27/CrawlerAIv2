import { useState } from "react";

/** Paging back and forth over an API that pages forward by cursor (SPEC-07 §4.6): the cursors of the pages before
 * are kept here, and the first page has none. */
export function useCursorPages() {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  return {
    /** The cursor of the page shown; null for the first. */
    cursor: cursors.at(-1) ?? null,
    /** The page shown, from 1. */
    page: cursors.length,
    /** Goes back a page; null on the first. */
    previous:
      cursors.length > 1
        ? () => {
            setCursors(cursors.slice(0, -1));
          }
        : null,
    /** Goes on to the page at `next` (a page's `next_cursor`); null on the last page. */
    nextTo: (next: string | null) =>
      next === null
        ? null
        : () => {
            setCursors([...cursors, next]);
          },
  };
}
