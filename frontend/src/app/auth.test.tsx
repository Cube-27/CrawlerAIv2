import { Button } from "@heroui/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { describe, expect, it } from "vite-plus/test";
import { problem, stubApi } from "../test/api";
import { useApiClient } from "./auth";
import { routes } from "./router";

// A screen that calls the API on demand, under the same route element as every screen.
function Probe() {
  const client = useApiClient();
  const [status, setStatus] = useState("idle");
  return (
    <>
      <Button
        onPress={() => {
          void client.GET("/v1/jobs").then(({ response }) => {
            setStatus(String(response.status));
          });
        }}
      >
        Call API
      </Button>
      <p>Status {status}</p>
    </>
  );
}

function renderProbe() {
  const root = routes[0];
  const gated = root?.children?.[0];
  const probe: RouteObject = {
    element: gated?.element,
    children: [...(gated?.children ?? []), { path: "probe", element: <Probe /> }],
  };
  const testRoutes: RouteObject[] = [{ element: root?.element, children: [probe] }];
  render(
    <RouterProvider router={createMemoryRouter(testRoutes, { initialEntries: ["/probe"] })} />,
  );
}

const SETUP_NOTICE = "The API rejected the request.";

describe("API access", () => {
  it("opens a screen with no key prompt and sends no credentials from the browser", async () => {
    const calls = stubApi({
      "GET /v1/jobs": () => Response.json({ items: [], next_cursor: null }),
    });
    renderProbe();

    await userEvent.click(screen.getByRole("button", { name: "Call API" }));

    expect(await screen.findByText("Status 200")).toBeInTheDocument();
    expect(calls.map((call) => call.authorization)).toEqual([null]);
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("shows the setup notice in the content area once the API answers 401", async () => {
    stubApi({
      "GET /v1/jobs": () => problem(401, { type: "unauthorized", title: "Unauthorized" }),
    });
    renderProbe();

    await userEvent.click(screen.getByRole("button", { name: "Call API" }));

    const main = screen.getByRole("main");
    expect(await screen.findByText(SETUP_NOTICE)).toBeInTheDocument();
    expect(main).toHaveTextContent(SETUP_NOTICE);
    expect(main).toHaveTextContent("Set CRAWLERAI_UI_API_KEY in .env");
    expect(screen.queryByRole("button", { name: "Call API" })).not.toBeInTheDocument();
  });
});
