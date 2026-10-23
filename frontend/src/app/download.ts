/** Saves `text` as a file named `filename` through the browser's download. The data was fetched with the API key, so
 * it is handed over as a Blob rather than as a link the browser would fetch without the key. */
export function saveText(filename: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  // Released after the click has started the download.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

/** Saves `value` as a JSON file named `filename`, as `saveText` does. */
export function saveJson(filename: string, value: unknown): void {
  saveText(filename, JSON.stringify(value, null, 2), "application/json");
}

/** Saves each page of a job's export (each a whole document) as its own file: `job-<id>.<extension>`, or
 * `job-<id>-<n>.<extension>` when there are several. Returns the file names. */
export function saveExportPages(
  jobId: string,
  { extension, type }: { extension: string; type: string },
  pages: readonly { content: string }[],
): string[] {
  return pages.map((page, index) => {
    const part = pages.length === 1 ? "" : `-${String(index + 1)}`;
    const filename = `job-${jobId}${part}.${extension}`;
    saveText(filename, page.content, type);
    return filename;
  });
}

/** Saves `blob` as a file named `filename`, as `saveText` does for text. */
export function saveBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
