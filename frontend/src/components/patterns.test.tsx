import { Button } from "@heroui/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vite-plus/test";
import { ConfirmDialog } from "./ConfirmDialog";
import { EmptyView } from "./EmptyView";
import { LoadingView } from "./LoadingView";
import { ProblemAlert } from "./ProblemAlert";
import { StatusLabel } from "./StatusLabel";
import { TablePagination } from "./TablePagination";

describe("StatusLabel", () => {
  it("shows the status as text with an icon, not by color alone", () => {
    const { container } = render(<StatusLabel text="Checked" tone="success" />);

    expect(screen.getByText("Checked")).toBeInTheDocument();
    expect(container.querySelector("svg[aria-hidden='true']")).not.toBeNull();
  });
});

describe("EmptyView and LoadingView", () => {
  it("say what is missing and how to get it", () => {
    render(<EmptyView title="No pages yet">Capture some first.</EmptyView>);

    expect(screen.getByText("No pages yet")).toBeInTheDocument();
    expect(screen.getByText("Capture some first.")).toBeInTheDocument();
  });

  it("names the loading spinner", () => {
    render(<LoadingView label="Loading pages" />);

    expect(screen.getByRole("status", { name: "Loading pages" })).toBeInTheDocument();
  });
});

describe("ConfirmDialog", () => {
  function renderDialog(onConfirm: () => void) {
    render(
      <ConfirmDialog
        trigger={<Button>Delete</Button>}
        title="Delete the job?"
        confirmLabel="Delete job"
        onConfirm={onConfirm}
      >
        Its records stay.
      </ConfirmDialog>,
    );
  }

  it("runs nothing when cancelled", async () => {
    const onConfirm = vi.fn<() => void>();
    renderDialog(onConfirm);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Its records stay.");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("runs the action once when confirmed, then closes", async () => {
    const onConfirm = vi.fn<() => void>();
    renderDialog(onConfirm);

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete job" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});

describe("TablePagination", () => {
  it("disables a direction the API returned no cursor for", async () => {
    const onNext = vi.fn<() => void>();
    render(<TablePagination summary="50 records" onPrevious={null} onNext={onNext} />);

    expect(screen.getByRole("button", { name: /Previous/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Next/ }));

    expect(onNext).toHaveBeenCalledTimes(1);
    expect(screen.getByText("50 records")).toBeInTheDocument();
  });
});

describe("ProblemAlert", () => {
  it("names each refused member, and gives a whole-request reason without one", () => {
    render(
      <ProblemAlert
        problem={{
          title: "Invalid request",
          detail: null,
          retryAfter: null,
          errors: [
            { field: "urls", reason: "at most 1000 URLs" },
            { field: "", reason: "records are asked alone" },
          ],
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Invalid requesturls: at most 1000 URLsrecords are asked alone",
    );
  });
});
