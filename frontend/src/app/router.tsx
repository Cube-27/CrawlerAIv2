import type { RouteObject } from "react-router";
import { HomeScreen } from "../screens/home/HomeScreen";
import { Shell } from "./shell";

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [{ index: true, element: <HomeScreen /> }],
  },
];
