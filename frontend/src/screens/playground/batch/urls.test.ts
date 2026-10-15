import { describe, expect, it } from "vite-plus/test";
import { lines } from "../pageRequest";
import { appendUrls, csvUrls } from "./urls";

describe("csvUrls", () => {
  it("reads the url column when the first record has that header", () => {
    const text = "name,URL\r\nFirst,https://shop.test/a\r\nSecond,https://shop.test/b\r\n";

    expect(csvUrls(text)).toEqual(["https://shop.test/a", "https://shop.test/b"]);
  });

  it("reads every record's first field when there is no url header, the first record too", () => {
    const text = "https://shop.test/a,first\nhttps://shop.test/b,second";

    expect(csvUrls(text)).toEqual(["https://shop.test/a", "https://shop.test/b"]);
  });

  it("reads quoted fields with commas, line breaks and doubled quotes as one field (RFC 4180)", () => {
    const text =
      'url,note\r\n"https://shop.test/a?x=1,2","say ""hi""\r\nagain"\r\n"https://shop.test/""q""",x\r\n';

    expect(csvUrls(text)).toEqual(["https://shop.test/a?x=1,2", 'https://shop.test/"q"']);
  });

  it("leaves out blank fields and blank lines", () => {
    expect(csvUrls("url\n\n  \nhttps://shop.test/a\n,\n")).toEqual(["https://shop.test/a"]);
  });
});

describe("appendUrls", () => {
  it("appends the new URLs after the list, dropping those already listed by exact string", () => {
    const list = "https://shop.test/a\nhttps://shop.test/b";

    expect(
      appendUrls(list, [
        "https://shop.test/b",
        "https://shop.test/c",
        "https://shop.test/B",
        "https://shop.test/c",
      ]),
    ).toBe("https://shop.test/a\nhttps://shop.test/b\nhttps://shop.test/c\nhttps://shop.test/B");
  });

  it("starts the list when it is empty", () => {
    expect(appendUrls("", ["https://shop.test/a"])).toBe("https://shop.test/a");
  });
});

describe("lines", () => {
  it("is the list's non-blank lines, trimmed", () => {
    expect(lines(" https://shop.test/a \r\n\n https://shop.test/b")).toEqual([
      "https://shop.test/a",
      "https://shop.test/b",
    ]);
  });
});
