import type { Endpoint } from "./endpoints";

/** Get code's snippets (SPEC-14 §4.7): the current request as cURL, Python (`httpx`) and an MCP tool call. Each is
 * generated from the request object, never by pasting user input into code: values are JSON-encoded, and shell words
 * are quoted per POSIX sh. */

/** The environment variable every snippet reads the API key from (SPEC-14 §4.7; the UI holds no key, §4.1). */
export const KEY_VARIABLE = "CRAWLERAI_API_KEY";

/** The request's body as the primary action sends it: JSON with a two-space indent. */
function json(body: object): string {
  return JSON.stringify(body, null, 2);
}

/** `text` as one POSIX sh word (POSIX.1-2017 XCU §2.2.3): inside single quotes nothing is special, and a single quote
 * ends the quoting, so each one is written as `'\''` (close, an escaped quote, reopen). */
export function shellWord(text: string): string {
  const escaped = text.replaceAll("'", String.raw`'\''`);
  return `'${escaped}'`;
}

/** `curl` sending the request to `origin`. The key stays a shell variable in double quotes, so the shell expands it. */
export function curlSnippet(origin: string, endpoint: Endpoint, body: object): string {
  return [
    `curl -X POST ${shellWord(origin + endpoint.path)} \\`,
    `  -H "Authorization: Bearer $${KEY_VARIABLE}" \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -d ${shellWord(json(body))}`,
  ].join("\n");
}

const INDENT = "    ";

/** A JSON value as a Python literal (Python Language Reference §2.4, §6.2): every JSON string escape is a Python
 * string escape too, so strings, numbers and member names stay JSON-encoded; only `true`, `false` and `null` are
 * spelled `True`, `False` and `None`. Nested values are indented four spaces per level (PEP 8). */
export function pythonLiteral(value: unknown, depth = 0): string {
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (Array.isArray(value))
    return pythonItems(
      value.map((entry) => pythonLiteral(entry, depth + 1)),
      ["[", "]"],
      depth,
    );
  if (typeof value === "object") {
    const members = Object.entries(value).map(
      ([key, entry]) => `${JSON.stringify(key)}: ${pythonLiteral(entry, depth + 1)}`,
    );
    return pythonItems(members, ["{", "}"], depth);
  }
  return JSON.stringify(value);
}

/** `items` between `open` and `close`, one per line at `depth + 1`, each followed by a comma (PEP 8's trailing
 * comma). */
function pythonItems(
  items: readonly string[],
  [open, close]: readonly [string, string],
  depth: number,
): string {
  if (items.length === 0) return open + close;
  const inner = INDENT.repeat(depth + 1);
  const lines = items.map((item) => `${inner}${item},\n`).join("");
  return `${open}\n${lines}${INDENT.repeat(depth)}${close}`;
}

/** A Python script sending the request with `httpx` and printing the answer. */
export function pythonSnippet(origin: string, endpoint: Endpoint, body: object): string {
  return [
    "import os",
    "",
    "import httpx",
    "",
    "response = httpx.request(",
    '    "POST",',
    `    ${JSON.stringify(origin + endpoint.path)},`,
    `    headers={"Authorization": f"Bearer {os.environ['${KEY_VARIABLE}']}"},`,
    `    json=${pythonLiteral(body, 1)},`,
    // A scrape waits for its page; httpx's own default (5 s) is shorter than many fetches.
    "    timeout=300.0,",
    ")",
    "response.raise_for_status()",
    "print(response.json())",
  ].join("\n");
}

/** The MCP `tools/call` request (MCP 2025-06-18, Tools; JSON-RPC 2.0) calling `tool` with the request as its `request`
 * argument, the shape every request tool of SPEC-10 §4.7 takes. */
export function mcpSnippet(tool: string, body: object): string {
  return json({
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: { name: tool, arguments: { request: body } },
  });
}
