import { vi } from "vite-plus/test";

/** A file the page handed to the browser's download: its name and its text. */
export interface SavedFile {
  name: string;
  text: Promise<string>;
}

/** Catches the downloads `saveText` starts (a Blob URL on a clicked link), in the order they start. */
export function catchDownloads(): SavedFile[] {
  const saved: SavedFile[] = [];
  const blobs = new Map<string, Blob>();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: (blob: Blob) => {
      const url = `blob:${String(blobs.size)}`;
      blobs.set(url, blob);
      return url;
    },
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push({ name: this.download, text: blobs.get(this.href)?.text() ?? Promise.resolve("") });
  });
  return saved;
}
