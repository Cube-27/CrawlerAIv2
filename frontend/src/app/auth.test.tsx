import { Button } from "@heroui/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { describe, expect, it, vi } from "vite-plus/test";
import { RequireKey, useApiClient } from "./auth";
import { routes } from "./router";

// A gated screen that calls the API on demand. The backend endpoints SPEC-07 defines don't exist yet, so the calls go
// to /healthz with `fetch` mocked to answer the way SPEC-07 §4.2–4.3 specifies.
function Probe() {
  const client = useApiClient();
  const [status, setStatus] = useState("idle");
  return (
    <>
      <Button
        onPress={() => {
          void client.GET("/healthz").then(({ response }) => {
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

function renderApp(path = "/") {
  const root = routes[0];
  const probe: RouteObject = {
    element: <RequireKey />,
    children: [{ path: "probe", element: <Probe /> }],
  };
  const testRoutes: RouteObject[] = [
    { element: root?.element, children: [...(root?.children ?? []), probe] },
  ];
  render(<RouterProvider router={createMemoryRouter(testRoutes, { initialEntries: [path] })} />);
}

function stubFetch(...responses: (() => Promise<Response>)[]) {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  for (const next of responses) fetchMock.mockImplementationOnce(next);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const ok = () => Promise.resolve(Response.json({ status: "ok" }));
const unauthorized = () =>
  Promise.resolve(
    new Response(
      JSON.stringify({
        type: "unauthorized",
        title: "Unauthorized",
        status: 401,
        detail: "The API key is revoked.",
      }),
      { status: 401, headers: { "content-type": "application/problem+json" } },
    ),
  );

async function connectWith(apiKey: string) {
  await userEvent.type(screen.getByLabelText(/API key/), apiKey);
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
}

function connectHeading() {
  return screen.getByRole("heading", { level: 1, name: "Connect" });
}

describe("key gate", () => {
  it("sends a viewer without a key to /connect, then back to the screen they asked for", async () => {
    renderApp("/probe");
    expect(connectHeading()).toBeInTheDocument();

    await connectWith("ck_first");

    expect(await screen.findByRole("button", { name: "Call API" })).toBeInTheDocument();
  });

  it("goes to the overview after connecting from /connect directly", async () => {
    renderApp("/connect");

    await connectWith("ck_first");

    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("refuses an empty or blank key", async () => {
    renderApp("/probe");

    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    await connectWith("   ");

    expect(connectHeading()).toBeInTheDocument();
    expect(screen.getByLabelText(/API key/)).toHaveAttribute("aria-invalid", "true");
  });

  it("sends the key, trimmed, as a bearer header and keeps it out of storage and cookies", async () => {
    const fetchMock = stubFetch(ok);
    renderApp("/probe");
    await connectWith("  ck_first ");

    await userEvent.click(await screen.findByRole("button", { name: "Call API" }));

    expect(await screen.findByText("Status 200")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0].headers.get("Authorization")).toBe("Bearer ck_first");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
  });

  it("drops the key on a 401 and shows the problem on /connect", async () => {
    const fetchMock = stubFetch(unauthorized, ok);
    renderApp("/probe");
    await connectWith("ck_revoked");

    await userEvent.click(await screen.findByRole("button", { name: "Call API" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Connect" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Unauthorized");
    expect(screen.getByRole("alert")).toHaveTextContent("The API key is revoked.");

    await connectWith("ck_second");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Call API" }));
    expect(await screen.findByText("Status 200")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1]?.[0].headers.get("Authorization")).toBe("Bearer ck_second");
  });

  it("shows a generic message when the 401 has no problem body", async () => {
    stubFetch(() => Promise.resolve(new Response(null, { status: 401 })));
    renderApp("/probe");
    await connectWith("ck_revoked");

    await userEvent.click(await screen.findByRole("button", { name: "Call API" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The API rejected the key.");
  });

  it("keeps a newer key when a 401 arrives for the key it replaced", async () => {
    let answerOld: (response: Response) => void = () => undefined;
    stubFetch(
      () =>
        new Promise((resolve) => {
          answerOld = resolve;
        }),
    );
    renderApp("/probe");
    await connectWith("ck_old");
    await userEvent.click(await screen.findByRole("button", { name: "Call API" }));

    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await connectWith("ck_new");
    answerOld(await unauthorized());

    expect(await screen.findByRole("button", { name: "Call API" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("forgets the key on disconnect", async () => {
    renderApp("/probe");
    await connectWith("ck_first");

    await userEvent.click(await screen.findByRole("button", { name: "Disconnect" }));

    expect(connectHeading()).toBeInTheDocument();
    expect(screen.getByLabelText(/API key/)).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });
});
