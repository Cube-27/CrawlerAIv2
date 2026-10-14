import { Button, Link, RouterProvider, Toast, ToggleButton, Typography } from "@heroui/react";
import {
  ArrowRightFromSquare,
  Database,
  Gear,
  Globe,
  House,
  Layers,
  ListUl,
  Magnifier,
  Moon,
  Sun,
  Tag,
  Thunderbolt,
} from "@gravity-ui/icons";
import type { ComponentType, SVGProps } from "react";
import { matchPath, Outlet, useHref, useLocation, useNavigate } from "react-router";
import { useEvalUi } from "../api/hooks/health";
import { useAuth } from "./auth";
import { useTheme } from "./theme";

interface NavEntry {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

interface NavGroup {
  /** The group's heading in the sidebar; the first group has none. */
  title: string | null;
  entries: NavEntry[];
}

const OVERVIEW: NavGroup = {
  title: null,
  entries: [{ href: "/", label: "Overview", icon: House }],
};

const EXTRACT: NavGroup = {
  title: "Extract",
  entries: [
    { href: "/scrape", label: "Scrape", icon: Magnifier },
    { href: "/jobs", label: "Jobs", icon: Thunderbolt },
    { href: "/records", label: "Records", icon: Database },
  ],
};

const CONFIGURE: NavGroup = {
  title: "Configure",
  entries: [
    { href: "/schemas", label: "Schemas", icon: Layers },
    { href: "/sites", label: "Sites", icon: Globe },
  ],
};

// With SPEC-03's screen, listed only when the backend serves the eval API (SPEC-12 §4.3).
const EVALUATE: NavGroup = {
  title: "Evaluate",
  entries: [{ href: "/labeling", label: "Labeling", icon: Tag }],
};

// Settings come last, at the foot of the sidebar.
const SETTINGS: NavEntry = { href: "/settings", label: "Settings", icon: Gear };

const WITHOUT_LABELING: NavGroup[] = [OVERVIEW, EXTRACT, CONFIGURE];
const WITH_LABELING: NavGroup[] = [...WITHOUT_LABELING, EVALUATE];

/** Whether `pathname` is in the section `href` opens: the page itself or, except for the overview, a page under it. */
function isCurrent(href: string, pathname: string): boolean {
  return matchPath({ path: href, end: href === "/" }, pathname) !== null;
}

function NavItem({ entry, pathname }: Readonly<{ entry: NavEntry; pathname: string }>) {
  const Icon = entry.icon;
  return (
    <li>
      {/* WAI-ARIA 1.2 `aria-current="page"`: the entry for the page shown; theme.css marks it. */}
      <Link
        href={entry.href}
        className="nav-item"
        aria-current={isCurrent(entry.href, pathname) ? "page" : false}
      >
        <Icon aria-hidden="true" />
        {entry.label}
      </Link>
    </li>
  );
}

function MainNav() {
  const { pathname } = useLocation();
  const groups = useEvalUi() ? WITH_LABELING : WITHOUT_LABELING;
  return (
    // At phone width the entries wrap in rows above the content (DESIGN.md, Layout); from `sm` they are a column
    // with Settings at the foot.
    <nav
      aria-label="Main"
      className="flex flex-row flex-wrap gap-1 sm:flex-1 sm:flex-col sm:flex-nowrap sm:gap-0"
    >
      {groups.map((group) => (
        <div key={group.title ?? "overview"} className="contents sm:block">
          {group.title === null ? null : (
            <p className="nav-heading hidden sm:block">{group.title}</p>
          )}
          <ul className="contents sm:flex sm:flex-col sm:gap-0.5">
            {group.entries.map((entry) => (
              <NavItem key={entry.href} entry={entry} pathname={pathname} />
            ))}
          </ul>
        </div>
      ))}
      <ul className="contents sm:mt-auto sm:flex sm:flex-col sm:pt-4">
        <NavItem entry={SETTINGS} pathname={pathname} />
      </ul>
    </nav>
  );
}

function SidebarFooter() {
  const [theme, setTheme] = useTheme();
  const { apiKey, disconnect } = useAuth();
  const dark = theme === "dark";
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
      {apiKey === null ? (
        <span />
      ) : (
        <Button variant="ghost" size="sm" onPress={disconnect}>
          <ArrowRightFromSquare aria-hidden="true" />
          Disconnect
        </Button>
      )}
      <ToggleButton
        isIconOnly
        size="sm"
        variant="ghost"
        aria-label="Dark theme"
        isSelected={dark}
        onChange={(selected) => {
          setTheme(selected ? "dark" : "light");
        }}
      >
        {dark ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
      </ToggleButton>
    </div>
  );
}

function Sidebar() {
  return (
    <aside
      aria-label="Sidebar"
      className="flex flex-col gap-3 border-b border-border p-3 sm:sticky sm:top-0 sm:h-dvh sm:w-sidebar sm:shrink-0 sm:border-b-0"
    >
      <div className="flex items-center gap-2.5 px-2 py-1">
        <span className="brand-mark" aria-hidden="true">
          <ListUl />
        </span>
        <Typography.Paragraph weight="semibold">CrawlerAI</Typography.Paragraph>
      </div>
      <MainNav />
      <SidebarFooter />
    </aside>
  );
}

export function Shell() {
  const navigate = useNavigate();
  return (
    // Lets HeroUI (React Aria) links navigate through react-router instead of reloading the page.
    <RouterProvider navigate={(to) => void navigate(to)} useHref={useHref}>
      <div className="flex min-h-dvh flex-col bg-background text-foreground sm:flex-row">
        <Sidebar />
        <main className="app-main min-w-0 flex-1">
          <div className="mx-auto max-w-content px-4 py-6 sm:px-8 sm:py-8">
            <Outlet />
          </div>
        </main>
        {/* The one toast region: screens notify with `toast` from @heroui/react (DESIGN.md, Patterns). */}
        <Toast.Provider />
      </div>
    </RouterProvider>
  );
}
