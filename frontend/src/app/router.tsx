import type { RouteObject } from "react-router";
import { ApiQueryProvider } from "../api/hooks/query";
import { JobScreen } from "../screens/jobs/JobScreen";
import { JobsScreen } from "../screens/jobs/JobsScreen";
import { RecordsScreen } from "../screens/records/RecordsScreen";
import { BatchPlayground } from "../screens/playground/batch/BatchPlayground";
import { CrawlPlayground } from "../screens/playground/crawl/CrawlPlayground";
import { MapPlayground } from "../screens/playground/map/MapPlayground";
import { ScrapePlayground } from "../screens/playground/scrape/ScrapePlayground";
import { SettingsScreen } from "../screens/settings/SettingsScreen";
import { ConfigScreen } from "../screens/sites/ConfigScreen";
import { SiteScreen } from "../screens/sites/SiteScreen";
import { SitesScreen } from "../screens/sites/SitesScreen";
import { EditSchemaScreen, NewSchemaScreen } from "../screens/schemas/SchemaEditScreens";
import { SchemaScreen } from "../screens/schemas/SchemaScreen";
import { SchemasScreen } from "../screens/schemas/SchemasScreen";
import { LabelingList } from "../screens/labeling/LabelingList";
import { LabelingPage } from "../screens/labeling/LabelingPage";
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
      // The server that serves the UI attaches the API key; a 401 shows the setup notice (SPEC-14 §4.1).
      {
        element: <RequireAccess />,
        children: [
          // The playground: `/` is its Scrape mode (SPEC-14 §4.8).
          { index: true, element: <ScrapePlayground /> },
          { path: "batch", element: <BatchPlayground /> },
          { path: "map", element: <MapPlayground /> },
          { path: "crawl", element: <CrawlPlayground /> },
          { path: "schemas", element: <SchemasScreen /> },
          { path: "schemas/new", element: <NewSchemaScreen /> },
          { path: "schemas/:id", element: <SchemaScreen /> },
          { path: "schemas/:id/edit", element: <EditSchemaScreen /> },
          { path: "records", element: <RecordsScreen /> },
          { path: "sites", element: <SitesScreen /> },
          { path: "sites/:host", element: <SiteScreen /> },
          { path: "configs/:id", element: <ConfigScreen /> },
          { path: "jobs", element: <JobsScreen /> },
          { path: "jobs/:id", element: <JobScreen /> },
          // SPEC-03 §4.10: the eval API takes the same API key as everything else. The shell lists these routes
          // when `/healthz` reports `eval_ui`.
          { path: "labeling", element: <LabelingList /> },
          { path: "labeling/:pageId", element: <LabelingPage /> },
          { path: "settings", element: <SettingsScreen /> },
        ],
      },
    ],
  },
];
