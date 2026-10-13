import type { RouteObject } from "react-router";
import { HomeScreen } from "../screens/home/HomeScreen";
import { LabelingList } from "../screens/labeling/LabelingList";
import { LabelingPage } from "../screens/labeling/LabelingPage";
import { listLoader, pageLoader } from "../screens/labeling/loaders";
import { Shell } from "./shell";

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      { index: true, element: <HomeScreen /> },
      // SPEC-03 §4.10. SPEC-12 PR 9 adds its nav entry, shown when the backend reports `eval_ui`.
      { path: "labeling", loader: listLoader, element: <LabelingList /> },
      { path: "labeling/:pageId", loader: pageLoader, element: <LabelingPage /> },
    ],
  },
];
