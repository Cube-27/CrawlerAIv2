import { Form } from "@heroui/react";
import type { ReactNode } from "react";
import { PageHeader } from "../../components/PageHeader";
import { CommandBar } from "./CommandBar";
import type { ModeId } from "./modes";
import { ModeSwitch } from "./ModeSwitch";

/** Every mode's page (SPEC-14 §4.2), top to bottom: the mode switch, the command bar (`input`, `tools`, `action`) in a
 * form whose errors are `validationErrors`, the inline options panel when open (`options`), then the output
 * (`children`). */
export function PlaygroundLayout({
  mode,
  validationErrors,
  onSubmit,
  input,
  tools,
  action,
  options,
  children,
}: Readonly<{
  mode: ModeId;
  validationErrors: Readonly<Record<string, string>>;
  onSubmit: () => void;
  input: ReactNode;
  tools: ReactNode;
  action: ReactNode;
  options: ReactNode;
  children: ReactNode;
}>) {
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Playground" />
      <ModeSwitch current={mode} />
      <Form
        className="flex flex-col gap-4"
        validationErrors={validationErrors}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <CommandBar input={input} tools={tools} action={action} />
        {options}
      </Form>
      {children}
    </section>
  );
}
