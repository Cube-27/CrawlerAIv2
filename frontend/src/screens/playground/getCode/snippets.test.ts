import { describe, expect, it } from "vite-plus/test";
import openapi from "../../../../openapi.json?raw";
import { MODES } from "../modes";
import { ENDPOINTS } from "./endpoints";
import { curlSnippet, shellWord } from "./snippets";
import { curlBody, shellWordAt } from "../../../test/shell";

const SCRAPE = ENDPOINTS.scrape;
const ORIGIN = "http://127.0.0.1:5173";

/** Values whose quoting goes wrong when built by concatenation: quotes, a newline, a backslash, `$` and backticks. */
const AWKWARD = [
  "",
  "it's",
  "''",
  'a "quoted" word',
  "two\nlines",
  String.raw`back\slash`,
  "$HOME and `date`",
  "émoji 🙂",
];

describe("shell quoting (POSIX sh single quotes)", () => {
  it("writes a single quote as close, escaped quote, reopen", () => {
    expect(shellWord("it's")).toBe(String.raw`'it'\''s'`);
  });

  it.each(AWKWARD)("reads %j back as the same word", (text) => {
    expect(shellWordAt(shellWord(text), 0)).toBe(text);
  });
});

describe("cURL", () => {
  it.each(AWKWARD)("sends %j in the body unchanged", (text) => {
    const body = { url: text, nested: { list: [text, null, true, 1.5] } };
    expect(curlBody(curlSnippet(ORIGIN, SCRAPE, body))).toEqual(body);
  });
});

interface Operation {
  summary: string;
  description: string;
}

describe("endpoints", () => {
  const paths = (JSON.parse(openapi) as { paths: Record<string, { post?: Operation }> }).paths;

  it.each(MODES.map((mode) => mode.id))(
    "%s names its OpenAPI operation's summary and first sentence",
    (mode) => {
      const endpoint = ENDPOINTS[mode];
      const operation = paths[endpoint.path]?.post;
      expect(operation?.summary).toBe(endpoint.title);
      const description = operation?.description.replaceAll(/\s+/g, " ") ?? "";
      expect(description.slice(0, endpoint.sentence.length)).toBe(endpoint.sentence);
    },
  );
});
