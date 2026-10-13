// XPath 1.0 (W3C REC-xpath-19991116) for an element of the labeled page, as SPEC-03 §4.10 asks: anchored at the
// nearest ancestor-or-self with a unique `id`, or else a unique `data-*` attribute (HTML §3.2.6.6), and positional
// steps below it. HTML element names are lower case in the HTML namespace, which XPath on an HTML document matches.

/** A string literal for `value`, or null when it holds both quote characters (XPath 1.0 has no escapes). */
function literal(value: string): string | null {
  if (!value.includes('"')) return `"${value}"`;
  if (!value.includes("'")) return `'${value}'`;
  return null;
}

function countWith(doc: Document, name: string, value: string): number {
  let n = 0;
  for (const element of doc.getElementsByTagName("*")) {
    if (element.getAttribute(name) === value) n += 1;
  }
  return n;
}

/** A step that selects `element` alone in its document, from its `id` or one of its `data-*` attributes. */
function anchor(element: Element): string | null {
  const doc = element.ownerDocument;
  const id = element.getAttribute("id");
  if (id !== null && id !== "") {
    const quoted = literal(id);
    if (quoted !== null && countWith(doc, "id", id) === 1) return `//*[@id=${quoted}]`;
  }
  for (const { name, value } of element.attributes) {
    if (!name.startsWith("data-") || value === "") continue;
    const quoted = literal(value);
    if (quoted !== null && countWith(doc, name, value) === 1) {
      return `//${element.localName}[@${name}=${quoted}]`;
    }
  }
  return null;
}

function step(element: Element): string {
  let position = 1;
  let same = 0;
  for (const sibling of element.parentElement?.children ?? []) {
    if (sibling.localName !== element.localName) continue;
    same += 1;
    if (sibling === element) position = same;
  }
  return same > 1 ? `${element.localName}[${String(position)}]` : element.localName;
}

/** An XPath that selects `element`, preferring an id or `data-*` anchor over a path from the root. */
export function xpathOf(element: Element): string {
  const steps: string[] = [];
  for (let at: Element | null = element; at !== null; at = at.parentElement) {
    const found = anchor(at);
    if (found !== null) return [found, ...steps].join("/");
    steps.unshift(step(at));
  }
  return `/${steps.join("/")}`;
}
