import { Button, Drawer, Typography } from "@heroui/react";
import type { FieldTypes } from "../../api/field";
import { problemOf } from "../../api/hooks/query";
import { useReplay } from "../../api/hooks/records";
import type { StoredRecord } from "../../api/records";
import { ProblemAlert } from "../../components/ProblemAlert";
import { RecordFieldsTable, RecordSummary } from "../../components/RecordFields";
import { ReplayView } from "./ReplayView";

/** The capture the record came from, and a replay of it with the current engine and config (SPEC-07 §4.6). */
function ReplaySection({
  record,
  fieldTypes,
}: Readonly<{ record: StoredRecord; fieldTypes: FieldTypes }>) {
  const replay = useReplay();
  const problem = problemOf(replay.error);
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Typography.Paragraph size="sm">
          Capture <Typography.Code>{record.capture_id}</Typography.Code>
        </Typography.Paragraph>
        <Button
          variant="secondary"
          isPending={replay.isPending}
          onPress={() => {
            replay.mutate(record.capture_id);
          }}
        >
          Replay
        </Button>
      </div>
      {problem === null ? null : <ProblemAlert problem={problem} />}
      {replay.isSuccess ? (
        <ReplayView stored={record} result={replay.data} fieldTypes={fieldTypes} />
      ) : null}
    </section>
  );
}

/** Every `field_meta` attribute of one record, and its capture with a replay (SPEC-12 §4.3), in a drawer over the
 * table. The record is not editable here; `onClose` closes the drawer. */
export function RecordInspector({
  record,
  fieldTypes,
  onClose,
}: Readonly<{ record: StoredRecord; fieldTypes: FieldTypes; onClose: () => void }>) {
  return (
    <Drawer
      isOpen
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose();
      }}
    >
      <Drawer.Backdrop>
        <Drawer.Content placement="bottom">
          <Drawer.Dialog>
            <Drawer.CloseTrigger />
            <Drawer.Header>
              <Drawer.Heading>Record version {record.version}</Drawer.Heading>
              <div className="flex flex-wrap items-center gap-3">
                <RecordSummary record={record} />
              </div>
            </Drawer.Header>
            <Drawer.Body className="flex flex-col gap-6">
              <RecordFieldsTable label="Record fields" record={record} fieldTypes={fieldTypes} />
              <ReplaySection record={record} fieldTypes={fieldTypes} />
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
