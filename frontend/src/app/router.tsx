import type { RouteObject } from "react-router";
import { ApiQueryProvider } from "../api/hooks/query";
import { ConnectScreen } from "../screens/connect/ConnectScreen";
import { HomeScreen } from "../screens/home/HomeScreen";
import { JobScreen } from "../screens/jobs/JobScreen";
import { JobsScreen } from "../screens/jobs/JobsScreen";
import { RecordsScreen } from "../screens/records/RecordsScreen";
import { ScrapeScreen } from "../screens/scrape/ScrapeScreen";
import { SettingsScreen } from "../screens/settings/SettingsScreen";
import { ConfigScreen } from "../screens/sites/ConfigScreen";
import { SiteScreen } from "../screens/sites/SiteScreen";
import { SitesScreen } from "../screens/sites/SitesScreen";
import { EditSchemaScreen, NewSchemaScreen } from "../screens/schemas/SchemaEditScreens";
import { SchemaScreen } from "../screens/schemas/SchemaScreen";
import { SchemasScreen } from "../screens/schemas/SchemasScreen";
import { LabelingList } from "../screens/labeling/LabelingList";
import { LabelingPage } from "../screens/labeling/LabelingPage";
import { AuthProvider, RequireKey } from "./auth";
import { Shell } from "./shell";

export const routes: RouteObject[] = [
  {
    element: (
      <AuthProvider>
        <ApiQueryProvider>
          <Shell />
        </ApiQueryProvider>
      </AuthProvider>
    ),
    children: [
      { path: "connect", element: <ConnectScreen /> },
      // Screens that call the API with the key (SPEC-12 §4.1: unauthenticated → /connect).
      {
        element: <RequireKey />,
        children: [
          { index: true, element: <HomeScreen /> },
          { path: "scrape", element: <ScrapeScreen /> },
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
