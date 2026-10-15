import { vi } from "vite-plus/test";

const SCHEME = "(prefers-color-scheme: dark)";

type Listener = (event: { matches: boolean; media: string }) => void;

/** jsdom has no matchMedia. Setup installs a light system scheme before each test; tests override it here. Returns a
 * function that changes the system scheme as an OS setting would, firing the query's `change` event (CSSOM View
 * §4.2). Every other query never matches. */
export function prefersDark(dark: boolean): (dark: boolean) => void {
  let current = dark;
  const listeners = new Set<Listener>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return current && query === SCHEME;
    },
    media: query,
    addEventListener: (_type: "change", listener: Listener) => {
      if (query === SCHEME) listeners.add(listener);
    },
    removeEventListener: (_type: "change", listener: Listener) => {
      listeners.delete(listener);
    },
  }));
  return (next) => {
    current = next;
    for (const listener of listeners) listener({ matches: next, media: SCHEME });
  };
}
