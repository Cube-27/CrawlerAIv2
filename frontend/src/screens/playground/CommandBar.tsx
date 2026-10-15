import { Card } from "@heroui/react";
import { use, type ReactNode } from "react";
import { ReadOnlyContext } from "./readOnly";

/** The command bar (SPEC-14 §4.2): one bordered surface with the mode's input on its first row and the toolbar under
 * it: the Options toggle and the tools on the left, the primary action on the right, so the action is at the top in
 * every mode. A read-only bar disables its input and tools (a disabled fieldset, HTML §4.10.15); the toggle and the
 * action stay usable. */
export function CommandBar({
  input,
  optionsToggle,
  tools,
  action,
}: Readonly<{ input: ReactNode; optionsToggle: ReactNode; tools: ReactNode; action: ReactNode }>) {
  const readOnly = use(ReadOnlyContext);
  return (
    <Card>
      <Card.Content className="flex flex-col gap-3">
        <fieldset disabled={readOnly} className="contents">
          {input}
        </fieldset>
        <div className="flex flex-wrap items-center gap-2">
          {optionsToggle}
          <fieldset disabled={readOnly} className="contents">
            {tools}
          </fieldset>
          <div className="ms-auto flex items-center gap-2">{action}</div>
        </div>
      </Card.Content>
    </Card>
  );
}
