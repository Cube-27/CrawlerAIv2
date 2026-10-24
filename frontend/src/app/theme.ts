import { useLayoutEffect, useState, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "snowcrawl.theme";

// Storage can be missing or throw (private windows, blocked site data); the theme is only a convenience.
function rememberedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function remember(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Not persisted; the choice still holds for this page load.
  }
}

const SYSTEM_DARK = "(prefers-color-scheme: dark)";

// The system scheme as an external store: Media Queries Level 5 `prefers-color-scheme`, which fires `change` when the
// viewer changes the OS setting (CSSOM View §4.2).
function subscribeToSystem(onChange: () => void): () => void {
  const query = window.matchMedia(SYSTEM_DARK);
  query.addEventListener("change", onChange);
  return () => {
    query.removeEventListener("change", onChange);
  };
}

function systemTheme(): Theme {
  return window.matchMedia(SYSTEM_DARK).matches ? "dark" : "light";
}

/** The viewer's theme, applied as `data-theme` on `<html>`: their choice,
 * else the system's scheme, followed live as it changes. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const [choice, setChoice] = useState<Theme | null>(rememberedTheme);
  const system = useSyncExternalStore(subscribeToSystem, systemTheme);
  const theme = choice ?? system;

  // Before paint, so a theme change never shows a frame in the old theme.
  useLayoutEffect(() => {
    document.documentElement.dataset["theme"] = theme;
  }, [theme]);

  // Only an explicit choice is remembered, so a viewer who never chose keeps following the system.
  function choose(next: Theme): void {
    remember(next);
    setChoice(next);
  }

  return [theme, choose];
}
