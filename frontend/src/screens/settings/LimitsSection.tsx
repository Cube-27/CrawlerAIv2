import {
  Button,
  Description,
  FieldError,
  Form,
  Label,
  NumberField,
  Switch,
  toast,
} from "@heroui/react";
import { useState } from "react";
import { problemOf } from "../../api/hooks/query";
import { useProjectSettings, useSaveProjectSettings } from "../../api/hooks/project";
import type { Problem } from "../../api/problem";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";
import { Section } from "../../components/Section";

/** What the form edits: the LLM call cap of a run whose request sets none, and whether a learned config waits for
 * approval before it serves (D-1342). */
type Edited = { llmCallCap: number | null; requireApproval: boolean };

/** The project's limits (`/v1/project/settings`): the LLM call cap of a run whose request sets none, and the approval
 * of learned configs. A save sends the key draft cap as loaded: only the API sets it. While the settings load, the
 * same form shows disabled, so loading moves nothing. */
export function LimitsSection() {
  const settings = useProjectSettings();
  const save = useSaveProjectSettings();
  const draftCap = settings.data?.draft_call_cap ?? null;
  return (
    <Section title="Limits">
      <LimitsForm
        // The form starts from the loaded values: it mounts again once the settings arrive.
        key={settings.isSuccess ? "loaded" : "loading"}
        saved={{
          llmCallCap: settings.data?.llm_call_cap ?? null,
          requireApproval: settings.data?.require_config_approval ?? false,
        }}
        isLoading={!settings.isSuccess}
        problem={problemOf(settings.error) ?? problemOf(save.error)}
        isPending={save.isPending}
        onSave={({ llmCallCap, requireApproval }) => {
          save.mutate(
            {
              llm_call_cap: llmCallCap,
              draft_call_cap: draftCap,
              require_config_approval: requireApproval,
            },
            {
              onSuccess: () => {
                toast.success("Saved the limits.");
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
  saved: Edited;
  isLoading: boolean;
  problem: Problem | null;
  isPending: boolean;
  onSave: (edited: Edited) => void;
}>) {
  // NaN is an empty NumberField: no limit.
  const [value, setValue] = useState(saved.llmCallCap ?? Number.NaN);
  const [requireApproval, setRequireApproval] = useState(saved.requireApproval);
  return (
    <Form
      className="flex flex-col gap-4 sm:max-w-md"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ llmCallCap: Number.isNaN(value) ? null : value, requireApproval });
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
      <div className="flex flex-col gap-1">
        <Switch
          name="require_config_approval"
          isSelected={requireApproval}
          isDisabled={isLoading}
          onChange={setRequireApproval}
        >
          <Switch.Content>
            <Switch.Control>
              <Switch.Thumb />
            </Switch.Control>
            <Label>Approve learned configs</Label>
          </Switch.Content>
        </Switch>
        <Description>
          A config learned for a site waits for your approval on its config page before it is used.
        </Description>
      </div>
      <FormActions>
        <Button type="submit" isPending={isPending} isDisabled={isLoading}>
          Save
        </Button>
      </FormActions>
    </Form>
  );
}
