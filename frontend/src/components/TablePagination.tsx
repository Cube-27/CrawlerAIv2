import { Pagination } from "@heroui/react";

/** Previous and next under a table. The API pages with a cursor (rest-api spec), so there are no page numbers: a
 * direction is enabled when the API returned a cursor for it. */
export function TablePagination({
  summary,
  onPrevious,
  onNext,
}: Readonly<{ summary: string; onPrevious: (() => void) | null; onNext: (() => void) | null }>) {
  return (
    <Pagination className="justify-end">
      <Pagination.Summary>{summary}</Pagination.Summary>
      <Pagination.Content>
        <Pagination.Item>
          <Pagination.Previous isDisabled={onPrevious === null} onPress={() => onPrevious?.()}>
            <Pagination.PreviousIcon />
            Previous
          </Pagination.Previous>
        </Pagination.Item>
        <Pagination.Item>
          <Pagination.Next isDisabled={onNext === null} onPress={() => onNext?.()}>
            Next
            <Pagination.NextIcon />
          </Pagination.Next>
        </Pagination.Item>
      </Pagination.Content>
    </Pagination>
  );
}
