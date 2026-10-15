/** The kinds of token a JSON view colors (RFC 8259 §3–7): object member names, strings, numbers, and the literals
 * `true`, `false` and `null`. Everything else (structure and whitespace) is plain. */
export type JsonTokenKind = "key" | "string" | "number" | "literal" | "plain";

export interface JsonToken {
  kind: JsonTokenKind;
  text: string;
  /** Where the token starts in the text: unique, so a list of tokens can key on it. */
  start: number;
}

// RFC 8259 §7 strings, §6 numbers and §3 literals, in JSON.stringify's output: a string is read whole before anything
// inside it could match, and a string followed by `:` is a member name (§4).
const TOKEN = /("(?:[^"\\]|\\.)*")(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g;

function kindOf(match: RegExpExecArray): JsonTokenKind {
  if (match[1] !== undefined) return match[2] === undefined ? "string" : "key";
  return /^-?\d/.test(match[0]) ? "number" : "literal";
}

function plain(text: string, start: number, end: number): JsonToken {
  return { kind: "plain", text: text.slice(start, end), start };
}

/** `text`, JSON as JSON.stringify writes it, cut into tokens; joined again they are `text`. */
export function jsonTokens(text: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  let last = 0;
  for (const match of text.matchAll(TOKEN)) {
    if (match.index > last) tokens.push(plain(text, last, match.index));
    const kind = kindOf(match);
    // A member name's `:` and the space before it are structure, not part of the name.
    const name = kind === "key" ? (match[1] ?? "") : match[0];
    tokens.push({ kind, text: name, start: match.index });
    last = match.index + match[0].length;
    if (name !== match[0]) tokens.push(plain(text, match.index + name.length, last));
  }
  if (last < text.length) tokens.push(plain(text, last, text.length));
  return tokens;
}
