import "@testing-library/jest-dom/vitest";
import { toast } from "@heroui/react";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vite-plus/test";
import { prefersDark } from "./media";

// jsdom has no ResizeObserver; HeroUI's toasts measure themselves with it. Layout is not under test here.
class NoResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

// jsdom has no Web Animations API; HeroUI's tab indicator reads `getAnimations` when the selected tab changes.
if (!("getAnimations" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "getAnimations", { value: (): Animation[] => [] });
}

beforeEach(() => {
  prefersDark(false);
  vi.stubGlobal("ResizeObserver", NoResizeObserver);
});

afterEach(() => {
  cleanup();
  // The toast queue is global: a toast from one test must not show in the next.
  toast.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
