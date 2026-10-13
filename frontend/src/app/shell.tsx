import { Button, Label, Link, RouterProvider, Switch } from "@heroui/react";
import { Outlet, useHref, useNavigate } from "react-router";
import { useAuth } from "./auth";
import { useTheme } from "./theme";

export function Shell() {
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const { apiKey, disconnect } = useAuth();

  return (
    // Lets HeroUI (React Aria) links navigate through react-router instead of reloading the page.
    <RouterProvider navigate={(to) => void navigate(to)} useHref={useHref}>
      <div className="min-h-dvh bg-background text-foreground">
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
          <span className="font-semibold">CrawlerAI</span>
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
        <div className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 py-6 sm:flex-row">
          <nav aria-label="Main" className="sm:w-48 sm:shrink-0">
            <ul className="flex flex-row gap-4 sm:flex-col sm:gap-2">
              <li>
                <Link href="/">Overview</Link>
              </li>
            </ul>
          </nav>
          <main className="min-w-0 flex-1">
            <Outlet />
          </main>
        </div>
      </div>
    </RouterProvider>
  );
}
