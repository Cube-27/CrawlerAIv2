import { describe, expect, it } from "vite-plus/test";
import { xpathOf } from "./xpath";

function page(body: string): Document {
  return new DOMParser().parseFromString(`<html><body>${body}</body></html>`, "text/html");
}

function only(doc: Document, selector: string): Element {
  const element = doc.querySelector(selector);
  if (element === null) throw new Error(`no ${selector}`);
  return element;
}

/** The elements `xpath` selects in `doc`, so each case checks the path selects exactly the clicked element. */
function select(doc: Document, xpath: string): Node[] {
  const result = doc.evaluate(xpath, doc, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  return Array.from({ length: result.snapshotLength }, (_, i) => result.snapshotItem(i) as Node);
}

describe("xpathOf", () => {
  it.each([
    ['<div><p>a</p><p class="x">b</p></div>', "p.x", "/html/body/div/p[2]"],
    [
      '<main id="m"><section><span>EUR 19.90</span></section></main>',
      "span",
      '//*[@id="m"]/section/span',
    ],
    ['<p id="p">Blue mug</p>', "#p", '//*[@id="p"]'],
    [
      '<ul><li data-sku="a1"><b>1</b></li><li data-sku="b2"><b>2</b></li></ul>',
      "[data-sku=b2] b",
      '//li[@data-sku="b2"]/b',
    ],
    ['<p id="d">1</p><p id="d"><i>2</i></p>', "p:nth-of-type(2) i", "/html/body/p[2]/i"],
    ["<p data-q='say \"hi\"'>x</p>", "p", "//p[@data-q='say \"hi\"']"],
  ])("in %s, %s is %s", (body, selector, expected) => {
    const doc = page(body);
    const element = only(doc, selector);

    const xpath = xpathOf(element);

    expect(xpath).toBe(expected);
    expect(select(doc, xpath)).toEqual([element]);
  });
});
