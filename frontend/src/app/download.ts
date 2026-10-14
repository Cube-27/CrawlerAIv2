/** Saves `value` as a JSON file named `filename` through the browser's download. The data was fetched with the API key,
 * so it is handed over as a Blob rather than as a link the browser would fetch without the key (SPEC-12 §4.1). */
export function saveJson(filename: string, value: unknown): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  // Released after the click has started the download.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
