import { Button, Form } from "@heroui/react";
import { useMemo, type ReactNode } from "react";
import { fieldErrors, type Problem } from "../../api/problem";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";

const NO_ERRORS: Readonly<Record<string, string>> = {};

/** A job dialog's form: the API's problem above the fields, its per-field errors next to the inputs they name, then
 * Cancel and the submit button. */
export function JobForm({
  submitLabel,
  problem,
  isPending,
  onCancel,
  onSubmit,
  children,
}: Readonly<{
  submitLabel: string;
  problem: Problem | null;
  isPending: boolean;
  onCancel: () => void;
  onSubmit: () => void;
  children: ReactNode;
}>) {
  const errors = useMemo(() => (problem === null ? NO_ERRORS : fieldErrors(problem)), [problem]);
  return (
    <Form
      className="flex flex-col gap-4"
      validationErrors={errors}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      {problem === null ? null : <ProblemAlert problem={problem} />}
      {children}
      <FormActions>
        <Button variant="tertiary" onPress={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isPending={isPending}>
          {submitLabel}
        </Button>
      </FormActions>
    </Form>
  );
}
