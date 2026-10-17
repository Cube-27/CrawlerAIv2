import { Button, FieldError, Input, Label, Modal, NumberField, TextField } from "@heroui/react";
import { Clock } from "@gravity-ui/icons";
import { useState } from "react";
import { useNavigate } from "react-router";
import { problemOf } from "../../api/hooks/query";
import { useCreateSchedule } from "../../api/hooks/schedules";
import { Choices } from "../../components/Choices";
import { ProblemAlert } from "../../components/ProblemAlert";
import {
  draftErrors,
  MIN_MINUTES,
  SCHEDULE_KINDS,
  scheduleBody,
  type ScheduleDraft,
} from "../schedules/cadence";
import { schedulePath } from "../schedules/paths";
import type { ModeId } from "./modes";

const EVERY = [
  ["interval", "Interval"],
  ["cron", "Cron expression"],
] as const;

/** The viewer's IANA time zone (ECMA-402 `resolvedOptions().timeZone`), the cron expression's default zone. */
function viewerZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function DraftFields({
  draft,
  errors,
  onChange,
}: Readonly<{
  draft: ScheduleDraft;
  errors: Readonly<Record<string, string>>;
  onChange: (draft: ScheduleDraft) => void;
}>) {
  return (
    <>
      <TextField
        name="name"
        isInvalid={"name" in errors}
        value={draft.name}
        onChange={(name) => {
          onChange({ ...draft, name });
        }}
      >
        <Label>Name</Label>
        <Input autoComplete="off" />
        <FieldError>{errors["name"]}</FieldError>
      </TextField>
      <Choices
        label="Runs"
        options={EVERY}
        value={draft.every}
        onChange={(every) => {
          onChange({ ...draft, every });
        }}
      />
      {draft.every === "interval" ? (
        <NumberField
          name="interval_s"
          isInvalid={"interval_s" in errors}
          value={draft.minutes}
          minValue={MIN_MINUTES}
          formatOptions={{ maximumFractionDigits: 0, useGrouping: false }}
          onChange={(minutes) => {
            onChange({ ...draft, minutes });
          }}
        >
          <Label>Every (minutes)</Label>
          <NumberField.Group>
            <NumberField.DecrementButton />
            <NumberField.Input />
            <NumberField.IncrementButton />
          </NumberField.Group>
          <FieldError>{errors["interval_s"]}</FieldError>
        </NumberField>
      ) : (
        <TextField
          name="cron"
          isInvalid={"cron" in errors}
          value={draft.cron}
          onChange={(cron) => {
            onChange({ ...draft, cron });
          }}
        >
          <Label>Cron expression (minute hour day month weekday)</Label>
          <Input autoComplete="off" spellCheck={false} placeholder="0 6 * * 1-5" />
          <FieldError>{errors["cron"]}</FieldError>
        </TextField>
      )}
      <TextField
        name="timezone"
        isInvalid={"timezone" in errors}
        value={draft.timezone}
        onChange={(timezone) => {
          onChange({ ...draft, timezone });
        }}
      >
        <Label>Time zone</Label>
        <Input autoComplete="off" spellCheck={false} />
        <FieldError>{errors["timezone"]}</FieldError>
      </TextField>
    </>
  );
}

/** The toolbar's Schedule this button (D-1418): a dialog that stores `request` (the body the mode's action would send;
 * null while the form can't be sent) as a recurring schedule (`POST /v1/schedules`) and opens it. Map runs no queued
 * job, so it has none. */
export function ScheduleThis({
  mode,
  request,
}: Readonly<{ mode: ModeId; request: object | null }>) {
  const kind = SCHEDULE_KINDS[mode];
  const navigate = useNavigate();
  const create = useCreateSchedule();
  const [draft, setDraft] = useState<ScheduleDraft>({
    name: "",
    every: "interval",
    minutes: 60,
    cron: "",
    timezone: viewerZone(),
  });
  const [checked, setChecked] = useState(false);
  if (kind === undefined) return null;
  const errors = checked ? draftErrors(draft) : {};
  const problem = problemOf(create.error);
  const save = () => {
    setChecked(true);
    if (request === null || Object.keys(draftErrors(draft)).length > 0) return;
    create.mutate(scheduleBody(kind, request, draft), {
      onSuccess: (schedule) => void navigate(schedulePath(schedule.id)),
    });
  };
  return (
    <Modal>
      <Button variant="secondary" isDisabled={request === null}>
        <Clock aria-hidden="true" />
        Schedule this
      </Button>
      <Modal.Backdrop>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>Schedule this request</Modal.Heading>
            </Modal.Header>
            {/* No form of its own: the dialog sits inside the playground's form in React's tree, where a submit
                would bubble to it and start the run. */}
            <Modal.Body className="flex flex-col gap-4">
              <DraftFields draft={draft} errors={errors} onChange={setDraft} />
              {problem === null ? null : <ProblemAlert problem={problem} />}
            </Modal.Body>
            <Modal.Footer>
              <Button isPending={create.isPending} onPress={save}>
                Create schedule
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
