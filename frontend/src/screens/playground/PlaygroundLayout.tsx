import { Button, Form } from "@heroui/react";
import { Pencil } from "@gravity-ui/icons";
import type { ReactNode } from "react";
import { PageHeader } from "../../components/PageHeader";
import { CommandBar } from "./CommandBar";
import type { ModeId } from "./modes";
import { ModeSwitch } from "./ModeSwitch";
import { OptionsToggle } from "./OptionsPanel";
import { ReadOnlyContext } from "./readOnly";

/** Every mode's page (SPEC-14 §4.2), top to bottom: the mode switch, the command bar (`input`, the Options toggle,
 * `tools`, `action`) in a form whose errors are `validationErrors`, the inline options panel (`options`) while
 * `optionsOpen`, then the output (`children`). The toggle shows a dot when `optionsChanged`. With `onEdit`, the page shows a run's request read-only, and the action is "Edit and
 * re-run", which calls it (SPEC-14 §4.8). */
export function PlaygroundLayout({
  mode,
  validationErrors,
  onSubmit,
  onEdit,
  input,
  optionsOpen,
  onOptionsOpen,
  optionsChanged,
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
  optionsOpen: boolean;
  onOptionsOpen: (isOpen: boolean) => void;
  optionsChanged: boolean;
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
            optionsToggle={
              <OptionsToggle
                isOpen={optionsOpen}
                changed={optionsChanged}
                onChange={onOptionsOpen}
              />
            }
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
          {optionsOpen ? options : null}
        </Form>
      </ReadOnlyContext>
      {children}
    </section>
  );
}
