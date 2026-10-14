import "@testing-library/jest-dom/vitest";
import { toast } from "@heroui/react";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vite-plus/test";
import { stubApi } from "./api";
import { prefersDark } from "./media";

// jsdom has no ResizeObserver; HeroUI's toasts measure themselves with it. Layout is not under test here.
class NoResizeObserver {
  observe(): void {
    // Nothing to observe: jsdom lays nothing out, so no size ever changes.
  }
  unobserve(): void {
    // Nothing is observed, so there is nothing to stop.
  }
  disconnect(): void {
    // Nothing is observed, so there is nothing to stop.
  }
}

// jsdom has no Web Animations API; HeroUI's tab indicator reads `getAnimations` when the selected tab changes.
if (!("getAnimations" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "getAnimations", { value: (): Animation[] => [] });
}

beforeEach(() => {
  prefersDark(false);
  vi.stubGlobal("ResizeObserver", NoResizeObserver);
  // Answers the shell's `/healthz` call for tests that stub no API; tests that do replace this `fetch`.
  stubApi({});
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
