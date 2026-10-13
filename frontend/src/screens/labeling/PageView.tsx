import { useLayoutEffect, useRef } from "react";
import { xpathOf } from "./xpath";

export interface Pick {
  text: string;
  locator: string; // `xpath:…`, a SPEC-03 §4.3 locator
}

/** The captured page, sanitized by the API, in a frame that runs no script (SPEC-03 §4.10). The frame shares this
 * page's origin only so that a click in it can be read here; without `allow-scripts` the page itself still runs
 * nothing, and a click never follows a link or submits a form. */
export function PageView({
  html,
  onPick,
}: Readonly<{ html: string; onPick: (pick: Pick) => void }>) {
  const frame = useRef<HTMLIFrameElement>(null);
  // The listener outlives renders; it calls the current `onPick`, which knows the field focused now.
  const pick = useRef(onPick);
  useLayoutEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  function listen(): void {
    const doc = frame.current?.contentDocument;
    const view = doc?.defaultView;
    if (doc == null || view == null) return;
    doc.addEventListener("click", (event) => {
      event.preventDefault();
      const element = event.target;
      if (!(element instanceof view.Element)) return;
      pick.current({
        text: element.textContent.replace(/\s+/g, " ").trim(),
        locator: `xpath:${xpathOf(element)}`,
      });
    });
  }

  return (
    <iframe
      ref={frame}
      title="Captured page"
      sandbox="allow-same-origin"
      srcDoc={html}
      onLoad={listen}
      className="h-page-view w-full rounded border border-border"
    />
  );
}
