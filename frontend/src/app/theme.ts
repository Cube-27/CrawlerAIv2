import { useLayoutEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "crawlerai.theme";

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

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** The viewer's theme, applied as `data-theme` on `<html>` (DESIGN.md; HeroUI v3 keys dark mode on it). */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => rememberedTheme() ?? systemTheme());

  // Before paint, so a theme change never shows a frame in the old theme.
  useLayoutEffect(() => {
    document.documentElement.dataset["theme"] = theme;
  }, [theme]);

  // Only an explicit choice is remembered, so a viewer who never chose keeps following the system.
  function choose(next: Theme): void {
    remember(next);
    setTheme(next);
  }

  return [theme, choose];
}
