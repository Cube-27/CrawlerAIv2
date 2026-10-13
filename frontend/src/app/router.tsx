import type { RouteObject } from "react-router";
import { ApiQueryProvider } from "../api/hooks/query";
import { ConnectScreen } from "../screens/connect/ConnectScreen";
import { HomeScreen } from "../screens/home/HomeScreen";
import { ScrapeScreen } from "../screens/scrape/ScrapeScreen";
import { EditSchemaScreen, NewSchemaScreen } from "../screens/schemas/SchemaEditScreens";
import { SchemaScreen } from "../screens/schemas/SchemaScreen";
import { SchemasScreen } from "../screens/schemas/SchemasScreen";
import { LabelingList } from "../screens/labeling/LabelingList";
import { LabelingPage } from "../screens/labeling/LabelingPage";
import { listLoader, pageLoader } from "../screens/labeling/loaders";
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
        ],
      },
      // SPEC-03 §4.10. The eval routes take no API key; SPEC-12 PR 9 adds the nav entry, shown when the backend
      // reports `eval_ui`.
      { path: "labeling", loader: listLoader, element: <LabelingList /> },
      { path: "labeling/:pageId", loader: pageLoader, element: <LabelingPage /> },
    ],
  },
];
