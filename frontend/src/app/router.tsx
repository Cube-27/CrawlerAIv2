import type { RouteObject } from "react-router";
import { ConnectScreen } from "../screens/connect/ConnectScreen";
import { HomeScreen } from "../screens/home/HomeScreen";
import { LabelingList } from "../screens/labeling/LabelingList";
import { LabelingPage } from "../screens/labeling/LabelingPage";
import { listLoader, pageLoader } from "../screens/labeling/loaders";
import { AuthProvider, RequireKey } from "./auth";
import { Shell } from "./shell";

export const routes: RouteObject[] = [
  {
    element: (
      <AuthProvider>
        <Shell />
      </AuthProvider>
    ),
    children: [
      { path: "connect", element: <ConnectScreen /> },
      // Screens that call the API with the key (SPEC-12 §4.1: unauthenticated → /connect).
      { element: <RequireKey />, children: [{ index: true, element: <HomeScreen /> }] },
      // SPEC-03 §4.10. The eval routes take no API key; SPEC-12 PR 9 adds the nav entry, shown when the backend
      // reports `eval_ui`.
      { path: "labeling", loader: listLoader, element: <LabelingList /> },
      { path: "labeling/:pageId", loader: pageLoader, element: <LabelingPage /> },
    ],
  },
];
