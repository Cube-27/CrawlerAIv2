// A 24-hour clock in the viewer's time zone: no AM/PM marker, so a column of times lines up.
const DATE_TIME = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** An API timestamp (RFC 3339) as a short local date and time, e.g. "Oct 14, 2026, 09:00". */
export function formatTimestamp(value: string): string {
  return DATE_TIME.format(new Date(value));
}

/** A timestamp as a `<time>` element: the readable date shows, and the exact instant is its `dateTime` and tooltip.
 * Null (not happened yet) shows as a dash. */
export function Timestamp({ value }: Readonly<{ value: string | null }>) {
  if (value === null) return "—";
  return (
    <time dateTime={value} title={value}>
      {formatTimestamp(value)}
    </time>
  );
}
