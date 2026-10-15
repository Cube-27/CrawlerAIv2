import { toast } from "@heroui/react";

/** Copies `text` to the clipboard and says so in a toast naming `what` ("the JSON"). The Clipboard API rejects without
 * permission or focus; the text stays on screen to select by hand. */
export function copyText(text: string, what: string): void {
  void navigator.clipboard.writeText(text).then(
    () => toast.success(`Copied ${what}.`),
    () => toast.danger("The browser did not allow copying."),
  );
}
