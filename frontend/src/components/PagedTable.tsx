import type { ReactNode } from "react";
import type { Problem } from "../api/problem";
import { LoadingView } from "./LoadingView";
import { ProblemAlert } from "./ProblemAlert";
import { TablePagination } from "./TablePagination";

/** Rows per page of every paged table: the box (`h-table-page` in theme.css) holds this many rows and the header. */
export const PAGE_SIZE = 20;

/** One page of a paged table and the pager under it. Every state (problem, loading, the page) fills the same box and
 * the pager stays under it, so paging moves nothing (owner's rule: no layout shift on interaction). `onNext` is null
 * until the page is known. */
export function PagedTable({
  problem,
  loading,
  page,
  onPrevious,
  onNext,
  children,
}: Readonly<{
  problem: Problem | null;
  /** The loading state's name, or null once the page is here. */
  loading: string | null;
  page: number;
  onPrevious: (() => void) | null;
  onNext: (() => void) | null;
  children: ReactNode;
}>) {
  let content = children;
  if (problem !== null) content = <ProblemAlert problem={problem} />;
  else if (loading !== null) content = <LoadingView label={loading} />;
  return (
    <div className="flex flex-col gap-3">
      <div className="h-table-page overflow-auto">{content}</div>
      <TablePagination summary={`Page ${String(page)}`} onPrevious={onPrevious} onNext={onNext} />
    </div>
  );
}
