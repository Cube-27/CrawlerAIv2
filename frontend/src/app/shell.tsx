import { Button, Label, Link, RouterProvider, Switch, Toast, Typography } from "@heroui/react";
import { matchPath, Outlet, useHref, useLocation, useNavigate } from "react-router";
import { useEvalUi } from "../api/hooks/health";
import { useAuth } from "./auth";
import { useTheme } from "./theme";

interface NavEntry {
  href: string;
  label: string;
}

const SCREENS: NavEntry[] = [
  { href: "/", label: "Overview" },
  { href: "/scrape", label: "Scrape" },
  { href: "/schemas", label: "Schemas" },
  { href: "/records", label: "Records" },
  { href: "/sites", label: "Sites" },
];

// With SPEC-03's screen, listed only when the backend serves the eval API (SPEC-12 §4.3).
const WITH_LABELING: NavEntry[] = [...SCREENS, { href: "/labeling", label: "Labeling" }];

/** Whether `pathname` is in the section `href` opens: the page itself or, except for the overview, a page under it. */
function isCurrent(href: string, pathname: string): boolean {
  return matchPath({ path: href, end: href === "/" }, pathname) !== null;
}

function MainNav() {
  const { pathname } = useLocation();
  const entries = useEvalUi() ? WITH_LABELING : SCREENS;
  return (
    <nav aria-label="Main" className="sm:w-48 sm:shrink-0">
      <ul className="flex flex-row flex-wrap gap-4 sm:flex-col sm:gap-2">
        {entries.map(({ href, label }) => (
          <li key={href}>
            {/* WAI-ARIA 1.2 `aria-current="page"`: the entry for the page shown; theme.css marks it. */}
            <Link href={href} aria-current={isCurrent(href, pathname) ? "page" : false}>
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Shell() {
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const { apiKey, disconnect } = useAuth();

  return (
    // Lets HeroUI (React Aria) links navigate through react-router instead of reloading the page.
    <RouterProvider navigate={(to) => void navigate(to)} useHref={useHref}>
      <div className="min-h-dvh bg-background text-foreground">
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
          <Typography.Paragraph weight="semibold">CrawlerAI</Typography.Paragraph>
          <div className="flex items-center gap-4">
            {apiKey === null ? null : (
              <Button variant="secondary" onPress={disconnect}>
                Disconnect
              </Button>
            )}
            <Switch
              isSelected={theme === "dark"}
              onChange={(dark) => {
                setTheme(dark ? "dark" : "light");
              }}
            >
              <Switch.Content>
                <Switch.Control>
                  <Switch.Thumb />
                </Switch.Control>
                <Label>Dark theme</Label>
              </Switch.Content>
            </Switch>
          </div>
        </header>
        <div className="mx-auto flex max-w-content flex-col gap-6 px-4 py-6 sm:flex-row">
          <MainNav />
          <main className="min-w-0 flex-1">
            <Outlet />
          </main>
        </div>
        {/* The one toast region: screens notify with `toast` from @heroui/react (DESIGN.md, Patterns). */}
        <Toast.Provider />
      </div>
    </RouterProvider>
  );
}
