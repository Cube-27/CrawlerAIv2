import { vi } from "vite-plus/test";

// jsdom has no matchMedia. Setup installs a light system scheme before each test; tests override it here.
export function prefersDark(dark: boolean): void {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: dark && query === "(prefers-color-scheme: dark)",
    media: query,
  }));
}
