import { Typography } from "@heroui/react";
import type { ReactNode } from "react";

/** A screen's compact title row, the same on every screen: the page's one h1 with its badges on the left (`children`)
 * and its primary actions on the right (`actions`). */
export function PageHeader({
  title,
  children,
  actions,
}: Readonly<{ title: string; children?: ReactNode; actions?: ReactNode }>) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Typography.Heading level={1}>{title}</Typography.Heading>
        {children}
      </div>
      {actions === undefined ? null : <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
