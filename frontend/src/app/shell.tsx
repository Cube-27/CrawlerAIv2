import { Link, RouterProvider, Toast, ToggleButton, Typography } from "@heroui/react";
import {
  Database,
  Gear,
  Globe,
  Clock,
  Layers,
  ListUl,
  Moon,
  Sun,
  Thunderbolt,
} from "@gravity-ui/icons";
import type { ComponentType, SVGProps } from "react";
import { matchPath, Outlet, useHref, useLocation, useNavigate } from "react-router";
import { MODES } from "../screens/playground/modes";
import { useTheme } from "./theme";

interface NavEntry {
  href: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

interface NavGroup {
  /** The group's heading in the sidebar. */
  title: string;
  entries: NavEntry[];
}

// One entry per playground mode, from the one list of modes, then the data screens; Settings come last,
// at the foot of the sidebar.
const PLAYGROUND: NavGroup = {
  title: "Playground",
  entries: [...MODES],
};

const DATA: NavGroup = {
  title: "Data",
  entries: [
    { href: "/jobs", label: "Jobs", icon: Thunderbolt },
    { href: "/schedules", label: "Schedules", icon: Clock },
    { href: "/records", label: "Records", icon: Database },
    { href: "/schemas", label: "Schemas", icon: Layers },
    { href: "/sites", label: "Sites", icon: Globe },
  ],
};

const SETTINGS: NavEntry = { href: "/settings", label: "Settings", icon: Gear };

const GROUPS: NavGroup[] = [PLAYGROUND, DATA];

/** Whether `pathname` is in the section `href` opens: the page itself or, except for `/`, a page under it. */
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
  return (
    // At phone width the entries wrap in rows above the content; from `sm` they are a column
    // with Settings at the foot.
    <nav
      aria-label="Main"
      className="flex flex-wrap gap-1 sm:flex-1 sm:flex-col sm:flex-nowrap sm:gap-0"
    >
      {GROUPS.map((group) => (
        <div key={group.title} className="contents sm:block">
          <p className="nav-heading hidden sm:block">{group.title}</p>
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
  const dark = theme === "dark";
  return (
    <div className="flex items-center gap-2 border-t border-border pt-3">
      <ToggleButton
        className="ms-auto"
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
      className="flex flex-col gap-3 border-b border-border p-3 sm:sticky sm:top-0 sm:h-dvh sm:w-sidebar sm:overflow-y-auto sm:shrink-0 sm:border-b-0"
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
          <div className="mx-auto max-w-content px-4 py-6 sm:px-gutter-x sm:py-gutter-y">
            <Outlet />
          </div>
        </main>
        {/* The one toast region: screens notify with `toast` from @heroui/react. */}
        <Toast.Provider />
      </div>
    </RouterProvider>
  );
}
