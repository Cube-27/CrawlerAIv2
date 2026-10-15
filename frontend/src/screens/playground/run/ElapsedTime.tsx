import { Typography } from "@heroui/react";
import { useEffect, useState } from "react";

const SECOND = 1000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** A duration as "12s", "4m 05s" or "1h 02m 03s"; negative counts as zero. */
export function elapsedText(ms: number): string {
  const total = Math.max(0, Math.floor(ms / SECOND));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${String(hours)}h ${pad(minutes)}m ${pad(seconds)}s`;
  if (minutes > 0) return `${String(minutes)}m ${pad(seconds)}s`;
  return `${String(seconds)}s`;
}

/** The time now, read again every second while `ticking`. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return undefined;
    const timer = setInterval(() => {
      setNow(Date.now());
    }, SECOND);
    return () => {
      clearInterval(timer);
    };
  }, [ticking]);
  return now;
}

/** How long a job has run: from its start to its end, or to now while it runs; a dash before it starts. */
export function ElapsedTime({
  startedAt,
  finishedAt,
}: Readonly<{ startedAt: string | null; finishedAt: string | null }>) {
  const now = useNow(startedAt !== null && finishedAt === null);
  const end = finishedAt === null ? now : Date.parse(finishedAt);
  return (
    <Typography.Paragraph size="sm" color="muted">
      Elapsed {startedAt === null ? "—" : elapsedText(end - Date.parse(startedAt))}
    </Typography.Paragraph>
  );
}
