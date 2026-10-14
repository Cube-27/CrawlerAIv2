import { Button, toast } from "@heroui/react";
import { useExportJob } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { ExportFormat, ExportPage } from "../../api/jobs";
import { saveText } from "../../app/download";
import { ProblemAlert } from "../../components/ProblemAlert";

// Each export format's label and file: RFC 8259 JSON, RFC 4180 CSV, RFC 7763 Markdown.
interface FileFormat {
  format: ExportFormat;
  label: string;
  extension: string;
  type: string;
}

const FORMATS: readonly FileFormat[] = [
  { format: "json_records", label: "Export JSON", extension: "json", type: "application/json" },
  { format: "csv_records", label: "Export CSV", extension: "csv", type: "text/csv" },
  { format: "markdown", label: "Export Markdown", extension: "md", type: "text/markdown" },
];

/** Saves each page of an export as its own file: `job-<id>.<ext>`, or `job-<id>-<n>.<ext>` when there are several. */
function save(
  jobId: string,
  { extension, type }: FileFormat,
  pages: readonly ExportPage[],
): string[] {
  return pages.map((page, index) => {
    const part = pages.length === 1 ? "" : `-${String(index + 1)}`;
    const filename = `job-${jobId}${part}.${extension}`;
    saveText(filename, page.content, type);
    return filename;
  });
}

/** The job's records exported by the server (SPEC-10 §4.2) and saved as files. A job without a schema has no records
 * to export; the server's problem says so. */
export function ExportActions({ jobId }: Readonly<{ jobId: string }>) {
  const exported = useExportJob(jobId);
  const problem = problemOf(exported.error);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap justify-end gap-2">
        {FORMATS.map((file) => (
          <Button
            key={file.format}
            variant="secondary"
            isPending={exported.isPending && exported.variables === file.format}
            isDisabled={exported.isPending}
            onPress={() => {
              exported.mutate(file.format, {
                onSuccess: (pages) => {
                  const files = save(jobId, file, pages);
                  toast.success(`Saved ${files.join(", ")}.`);
                },
              });
            }}
          >
            {file.label}
          </Button>
        ))}
      </div>
      {problem === null ? null : <ProblemAlert problem={problem} />}
    </div>
  );
}
