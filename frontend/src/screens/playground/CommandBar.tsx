import { Card } from "@heroui/react";
import type { ReactNode } from "react";

/** The command bar (SPEC-14 §4.2): one bordered surface with the mode's input on its first row and the toolbar under
 * it, the tools on the left and the primary action on the right, so the action is at the top in every mode. */
export function CommandBar({
  input,
  tools,
  action,
}: Readonly<{ input: ReactNode; tools: ReactNode; action: ReactNode }>) {
  return (
    <Card>
      <Card.Content className="flex flex-col gap-3">
        {input}
        <div className="flex flex-wrap items-center gap-2">
          {tools}
          <div className="ms-auto flex items-center gap-2">{action}</div>
        </div>
      </Card.Content>
    </Card>
  );
}
