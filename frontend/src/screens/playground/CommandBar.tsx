import { Card } from "@heroui/react";
import { use, type ReactNode } from "react";
import { ReadOnlyContext } from "./readOnly";

/** The command bar (SPEC-14 §4.2): one bordered surface with the mode's input on top and the toolbar under it: the
 * Options button and the tools on the left, the primary action on the right. The input sits in a box of at least
 * `min-h-playground-input`, which holds a URL and its error, so switching between the single-URL modes or showing an
 * error moves neither the toolbar nor the action; Batch's ten-line list is taller (D-1213). A read-only bar disables its input and tools (a disabled fieldset,
 * HTML §4.10.15); Options and the action stay usable. */
export function CommandBar({
  input,
  options,
  tools,
  action,
}: Readonly<{ input: ReactNode; options: ReactNode; tools: ReactNode; action: ReactNode }>) {
  const readOnly = use(ReadOnlyContext);
  return (
    <Card>
      <Card.Content className="flex flex-col gap-3">
        <fieldset disabled={readOnly} className="min-h-playground-input">
          {input}
        </fieldset>
        {/* At least as tall as a select, so a mode without one (Map) keeps the action where the others have it. */}
        <div className="flex min-h-10 flex-wrap items-center gap-2">
          {options}
          <fieldset disabled={readOnly} className="contents">
            {tools}
          </fieldset>
          <div className="ms-auto flex items-center gap-2">{action}</div>
        </div>
      </Card.Content>
    </Card>
  );
}
