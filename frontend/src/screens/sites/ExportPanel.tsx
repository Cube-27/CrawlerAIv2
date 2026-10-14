import { Button, Form, Table, Typography, toast } from "@heroui/react";
import { useState } from "react";
import type { ConfigDetail, ExportFormat, ReleaseField, ReleaseReport } from "../../api/configs";
import { useExportConfig } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { saveJson } from "../../app/download";
import { Choices } from "../../components/Choices";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";
import { StatusLabel } from "../../components/StatusLabel";

const FORMATS: readonly (readonly [ExportFormat, string])[] = [
  ["json", "Config IR (JSON)"],
  ["platform_draft", "Platform draft"],
];

// SPEC-08 §4.12: a `manual` field is one the release executor did not reproduce; it needs hand work after export.
function ReleaseOutcome({ field }: Readonly<{ field: ReleaseField }>) {
  return field.manual ? (
    <StatusLabel text="manual" tone="warning" />
  ) : (
    <StatusLabel text="reproduced" tone="success" />
  );
}

/** The release check of an export: each field's reproduction on the held-out pages, `manual` ones marked. */
export function ReleaseReportView({ report }: Readonly<{ report: ReleaseReport }>) {
  const { listing } = report;
  // A field name is `[a-z][a-z0-9_]*` (SPEC-04), so "next page" never hides one.
  const fields = {
    ...report.fields,
    ...listing?.fields,
    ...(listing?.next == null ? {} : { "next page": listing.next }),
  };
  const rows = Object.entries(fields).map(([name, field]) => ({ id: name, field }));
  return (
    <div className="flex flex-col gap-3">
      <Typography.Paragraph>
        Release check on {report.held_out.length} held-out pages.
      </Typography.Paragraph>
      <Table>
        <Table.ScrollContainer>
          <Table.Content aria-label="Release report">
            <Table.Header>
              <Table.Column isRowHeader>Field</Table.Column>
              <Table.Column>Release</Table.Column>
              <Table.Column>Reproduced</Table.Column>
            </Table.Header>
            <Table.Body items={rows}>
              {({ id, field }) => (
                <Table.Row id={id}>
                  <Table.Cell>{id}</Table.Cell>
                  <Table.Cell>
                    <ReleaseOutcome field={field} />
                  </Table.Cell>
                  <Table.Cell>
                    {field.reproduced}/{field.published}
                  </Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </div>
  );
}

/** Exports the config in a chosen format (SPEC-08 §4.11), saves it as a file and shows its release report. */
export function ExportPanel({ config }: Readonly<{ config: ConfigDetail }>) {
  const [format, setFormat] = useState<ExportFormat>("json");
  const exported = useExportConfig(config.id);
  const problem = problemOf(exported.error);
  return (
    <div className="flex flex-col gap-4">
      <Form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          exported.mutate(format, {
            onSuccess: (answer) => {
              const { site, version } = config;
              const filename = `${site}-v${String(version)}-${answer.format}.json`;
              saveJson(filename, answer.export);
              toast.success(`Saved ${filename}.`);
            },
          });
        }}
      >
        {problem === null ? null : <ProblemAlert problem={problem} />}
        <Choices label="Format" options={FORMATS} value={format} onChange={setFormat} />
        <FormActions>
          <Button type="submit" isPending={exported.isPending}>
            Export
          </Button>
        </FormActions>
      </Form>
      {exported.isSuccess ? <ReleaseReportView report={exported.data.release} /> : null}
    </div>
  );
}
