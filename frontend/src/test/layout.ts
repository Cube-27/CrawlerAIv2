import { onTestFinished } from "vite-plus/test";

/** jsdom does no layout. For the rest of the running test, every element gets a box `box` px wide and text
 * `character` px per character, so text longer than `box / character` characters is cut off (CSSOM View
 * `scrollWidth` > `clientWidth`). */
export function stubTextLayout(box = 100, character = 10): void {
  const saved = {
    scrollWidth: Object.getOwnPropertyDescriptor(Element.prototype, "scrollWidth"),
    clientWidth: Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth"),
  };
  Object.defineProperty(Element.prototype, "scrollWidth", {
    configurable: true,
    get(this: Element) {
      return this.textContent.length * character;
    },
  });
  Object.defineProperty(Element.prototype, "clientWidth", { configurable: true, get: () => box });
  onTestFinished(() => {
    for (const [name, descriptor] of Object.entries(saved)) {
      if (descriptor !== undefined) Object.defineProperty(Element.prototype, name, descriptor);
    }
  });
}
