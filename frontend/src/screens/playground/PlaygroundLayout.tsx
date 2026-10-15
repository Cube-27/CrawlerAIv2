import { Button, Form } from "@heroui/react";
import { Pencil } from "@gravity-ui/icons";
import type { ReactNode } from "react";
import { PageHeader } from "../../components/PageHeader";
import { CommandBar } from "./CommandBar";
import type { ModeId } from "./modes";
import { ModeSwitch } from "./ModeSwitch";
import { ReadOnlyContext } from "./readOnly";

/** Every mode's page (SPEC-14 §4.2), top to bottom: the mode switch, the command bar (`input`, `optionsToggle`,
 * `tools`, `action`) in a form whose errors are `validationErrors`, the inline options panel when open (`options`),
 * then the output (`children`). With `onEdit`, the page shows a run's request read-only, and the action is "Edit and
 * re-run", which calls it (SPEC-14 §4.8). */
export function PlaygroundLayout({
  mode,
  validationErrors,
  onSubmit,
  onEdit,
  input,
  optionsToggle,
  tools = null,
  action,
  options,
  children,
}: Readonly<{
  mode: ModeId;
  validationErrors: Readonly<Record<string, string>>;
  onSubmit: () => void;
  onEdit: (() => void) | null;
  input: ReactNode;
  optionsToggle: ReactNode;
  tools?: ReactNode;
  action: ReactNode;
  options: ReactNode;
  children: ReactNode;
}>) {
  const readOnly = onEdit !== null;
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Playground" />
      <ModeSwitch current={mode} />
      <ReadOnlyContext value={readOnly}>
        <Form
          className="flex flex-col gap-4"
          validationErrors={validationErrors}
          onSubmit={(event) => {
            event.preventDefault();
            if (!readOnly) onSubmit();
          }}
        >
          <CommandBar
            input={input}
            optionsToggle={optionsToggle}
            tools={tools}
            action={
              onEdit === null ? (
                action
              ) : (
                <Button variant="secondary" onPress={onEdit}>
                  <Pencil aria-hidden="true" />
                  Edit and re-run
                </Button>
              )
            }
          />
          {options}
        </Form>
      </ReadOnlyContext>
      {children}
    </section>
  );
}
