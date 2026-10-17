import { Button, Description, FieldError, Form, Label, NumberField, toast } from "@heroui/react";
import { useState } from "react";
import { problemOf } from "../../api/hooks/query";
import { useProjectSettings, useSaveProjectSettings } from "../../api/hooks/project";
import type { Problem } from "../../api/problem";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";
import { Section } from "../../components/Section";

/** The project's limits (`/v1/project/settings`): the LLM call cap of a run whose request sets none. A save sends the
 * key draft cap as loaded: only the API sets it. While the settings load, the same form shows disabled, so loading
 * moves nothing. */
export function LimitsSection() {
  const settings = useProjectSettings();
  const save = useSaveProjectSettings();
  const saved = settings.data?.llm_call_cap;
  const draftCap = settings.data?.draft_call_cap ?? null;
  return (
    <Section title="Limits">
      <LimitsForm
        // The form starts from the loaded value: it mounts again once the settings arrive.
        key={settings.isSuccess ? "loaded" : "loading"}
        saved={saved ?? null}
        isLoading={!settings.isSuccess}
        problem={problemOf(settings.error) ?? problemOf(save.error)}
        isPending={save.isPending}
        onSave={(llmCallCap) => {
          save.mutate(
            { llm_call_cap: llmCallCap, draft_call_cap: draftCap },
            {
              onSuccess: () => {
                toast.success("Saved the LLM call limit.");
              },
            },
          );
        }}
      />
    </Section>
  );
}

function LimitsForm({
  saved,
  isLoading,
  problem,
  isPending,
  onSave,
}: Readonly<{
  saved: number | null;
  isLoading: boolean;
  problem: Problem | null;
  isPending: boolean;
  onSave: (llmCallCap: number | null) => void;
}>) {
  // NaN is an empty NumberField: no limit.
  const [value, setValue] = useState(saved ?? Number.NaN);
  return (
    <Form
      className="flex flex-col gap-4 sm:max-w-md"
      onSubmit={(event) => {
        event.preventDefault();
        onSave(Number.isNaN(value) ? null : value);
      }}
    >
      {problem === null ? null : <ProblemAlert problem={problem} />}
      <NumberField
        name="llm_call_cap"
        value={value}
        minValue={0}
        isDisabled={isLoading}
        formatOptions={{ maximumFractionDigits: 0, useGrouping: false }}
        onChange={setValue}
      >
        <Label>LLM call limit per run</Label>
        <NumberField.Group>
          <NumberField.DecrementButton />
          <NumberField.Input placeholder="No limit" />
          <NumberField.IncrementButton />
        </NumberField.Group>
        <Description>
          The most LLM calls a run may make when it sets no limit of its own. Empty: no limit.
        </Description>
        <FieldError />
      </NumberField>
      <FormActions>
        <Button type="submit" isPending={isPending} isDisabled={isLoading}>
          Save
        </Button>
      </FormActions>
    </Form>
  );
}
