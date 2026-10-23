import type { RouteObject } from "react-router";
import { ApiQueryProvider } from "../api/hooks/query";
import { JobScreen } from "../screens/jobs/JobScreen";
import { JobsScreen } from "../screens/jobs/JobsScreen";
import { RecordsScreen } from "../screens/records/RecordsScreen";
import { BatchPlayground } from "../screens/playground/batch/BatchPlayground";
import { CrawlPlayground } from "../screens/playground/crawl/CrawlPlayground";
import { ExtractPlayground } from "../screens/playground/extract/ExtractPlayground";
import { SearchPlayground } from "../screens/playground/search/SearchPlayground";
import { MapPlayground } from "../screens/playground/map/MapPlayground";
import { ScrapePlayground } from "../screens/playground/scrape/ScrapePlayground";
import { ScheduleScreen } from "../screens/schedules/ScheduleScreen";
import { SchedulesScreen } from "../screens/schedules/SchedulesScreen";
import { SettingsScreen } from "../screens/settings/SettingsScreen";
import { ConfigScreen } from "../screens/sites/ConfigScreen";
import { SiteScreen } from "../screens/sites/SiteScreen";
import { SitesScreen } from "../screens/sites/SitesScreen";
import { EditSchemaScreen, NewSchemaScreen } from "../screens/schemas/SchemaEditScreens";
import { SchemaScreen } from "../screens/schemas/SchemaScreen";
import { SchemasScreen } from "../screens/schemas/SchemasScreen";
import { AccessProvider, RequireAccess } from "./auth";
import { Shell } from "./shell";

export const routes: RouteObject[] = [
  {
    element: (
      <AccessProvider>
        <ApiQueryProvider>
          <Shell />
        </ApiQueryProvider>
      </AccessProvider>
    ),
    children: [
      // The server that serves the UI attaches the API key; a 401 shows the setup notice.
      {
        element: <RequireAccess />,
        children: [
          // The playground: `/` is its Scrape mode.
          { index: true, element: <ScrapePlayground /> },
          { path: "batch", element: <BatchPlayground /> },
          { path: "map", element: <MapPlayground /> },
          { path: "crawl", element: <CrawlPlayground /> },
          { path: "search", element: <SearchPlayground /> },
          { path: "extract", element: <ExtractPlayground /> },
          { path: "schemas", element: <SchemasScreen /> },
          { path: "schemas/new", element: <NewSchemaScreen /> },
          { path: "schemas/:id", element: <SchemaScreen /> },
          { path: "schemas/:id/edit", element: <EditSchemaScreen /> },
          { path: "records", element: <RecordsScreen /> },
          { path: "sites", element: <SitesScreen /> },
          { path: "sites/:host", element: <SiteScreen /> },
          { path: "configs/:id", element: <ConfigScreen /> },
          { path: "jobs", element: <JobsScreen /> },
          // A job a mode runs redirects to its run there; a `learn` job keeps its page.
          { path: "jobs/:id", element: <JobScreen /> },
          { path: "schedules", element: <SchedulesScreen /> },
          { path: "schedules/:id", element: <ScheduleScreen /> },
          { path: "settings", element: <SettingsScreen /> },
        ],
      },
    ],
  },
];
