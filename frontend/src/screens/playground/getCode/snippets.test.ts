import { describe, expect, it } from "vite-plus/test";
import openapi from "../../../../openapi.json?raw";
import { MODES } from "../modes";
import { ENDPOINTS } from "./endpoints";
import { agentPrompts } from "./prompts";
import { curlSnippet, mcpSnippet, pythonLiteral, pythonSnippet, shellWord } from "./snippets";
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
  it("posts the JSON body with the key from the environment", () => {
    expect(
      curlSnippet(ORIGIN, SCRAPE, { url: "https://example.com/", formats: ["markdown"] }),
    ).toBe(
      [
        "curl -X POST 'http://127.0.0.1:5173/v1/scrape' \\",
        '  -H "Authorization: Bearer $CRAWLERAI_API_KEY" \\',
        "  -H 'Content-Type: application/json' \\",
        `  -d '{`,
        `  "url": "https://example.com/",`,
        `  "formats": [`,
        `    "markdown"`,
        `  ]`,
        `}'`,
      ].join("\n"),
    );
  });

  it.each(AWKWARD)("sends %j in the body unchanged", (text) => {
    const body = { url: text, nested: { list: [text, null, true, 1.5] } };
    expect(curlBody(curlSnippet(ORIGIN, SCRAPE, body))).toEqual(body);
  });
});

describe("Python", () => {
  it("writes JSON values as Python literals, strings JSON-encoded", () => {
    expect(
      pythonLiteral({ a: true, b: false, c: null, d: [], e: {}, f: ['it\'s "x"\n'], g: 2 }),
    ).toBe(
      [
        "{",
        '    "a": True,',
        '    "b": False,',
        '    "c": None,',
        '    "d": [],',
        '    "e": {},',
        '    "f": [',
        String.raw`        "it's \"x\"\n",`,
        "    ],",
        '    "g": 2,',
        "}",
      ].join("\n"),
    );
  });

  it("posts the body with httpx and the key from the environment", () => {
    expect(pythonSnippet(ORIGIN, ENDPOINTS.map, { url: "https://example.com/" })).toBe(
      [
        "import os",
        "",
        "import httpx",
        "",
        "response = httpx.post(",
        '    "http://127.0.0.1:5173/v1/map",',
        `    headers={"Authorization": f"Bearer {os.environ['CRAWLERAI_API_KEY']}"},`,
        "    json={",
        '        "url": "https://example.com/",',
        "    },",
        "    timeout=300.0,",
        ")",
        "response.raise_for_status()",
        "print(response.json())",
      ].join("\n"),
    );
  });
});

describe("MCP", () => {
  it("calls the tool with the body as its request argument", () => {
    const body = { url: "https://example.com/" };
    expect(JSON.parse(mcpSnippet("map", body))).toEqual({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: "map", arguments: { request: body } },
    });
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

describe("agent prompts", () => {
  it.each(MODES.map((mode) => mode.id))("%s has the two prompts, each with text", (mode) => {
    const prompts = agentPrompts(mode);
    expect(prompts.map(({ title, name }) => [title, name])).toEqual([
      ["Use it with coding agents", `call-${mode}`],
      ["Build on top of it", `integrate-${mode}`],
    ]);
    for (const prompt of prompts) {
      expect(prompt.text).toContain(ENDPOINTS[mode].path);
      expect(prompt.text).not.toMatch(/^# /m);
    }
  });
});
