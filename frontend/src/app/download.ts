/** Saves `text` as a file named `filename` through the browser's download. The data was fetched with the API key, so
 * it is handed over as a Blob rather than as a link the browser would fetch without the key (SPEC-12 §4.1). */
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
