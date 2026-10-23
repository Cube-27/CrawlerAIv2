import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vite-plus/test";
import type { WebhookDelivery } from "../../../api/jobs";
import { jobSummary, storedBatch } from "../../../test/jobs";
import { openPlayground } from "../../../test/playground";
import { runApi } from "../../../test/runs";

// `fetch` answers `GET /v1/jobs/{id}/webhook-deliveries` as the API defines it.

const JOB_ID = "0192a000-0000-7000-8000-00000000d0b1";
const DELIVERIES = `GET /v1/jobs/${JOB_ID}/webhook-deliveries`;

function delivery(
  overrides: Partial<WebhookDelivery> & Pick<WebhookDelivery, "id">,
): WebhookDelivery {
  return {
    status: "delivered",
    attempts: 1,
    next_attempt_at: null,
    last_error: null,
    response_code: 204,
    event_count: 1,
    created_at: "2026-10-17T09:00:00Z",
    ...overrides,
  };
}

function batchRun(replies: Parameters<typeof runApi>[1], webhookUrl: string | null) {
  return runApi(
    {
      submit: "POST /v1/batch/scrape",
      jobId: JOB_ID,
      kind: "batch_scrape",
      job: jobSummary({ id: JOB_ID, kind: "batch_scrape", webhook_url: webhookUrl }),
      request: storedBatch({ urls: ["https://shop.test/a"], webhook_url: webhookUrl }),
    },
    replies,
  );
}

async function openDeliveries() {
  await openPlayground(`/batch?job=${JOB_ID}`);
  await userEvent.click(await screen.findByRole("button", { name: "Deliveries" }));
  return within(await screen.findByRole("grid", { name: "Webhook deliveries" }));
}

describe("webhook deliveries of a run", () => {
  it("lists each delivery's status, attempts, the receiver's status and the last error", async () => {
    batchRun(
      {
        [DELIVERIES]: () =>
          Response.json({
            items: [
              delivery({
                id: "0192a000-0000-7000-8000-00000000d002",
                status: "pending",
                attempts: 2,
                response_code: 503,
                last_error: "status 503",
                next_attempt_at: "2026-10-17T09:05:00Z",
              }),
              delivery({
                id: "0192a000-0000-7000-8000-00000000d001",
                status: "failed",
                attempts: 5,
                response_code: null,
                last_error: "connection refused",
                event_count: 3,
              }),
            ],
            next_cursor: null,
          }),
      },
      "https://hooks.test/in",
    );

    const table = await openDeliveries();

    const pending = table.getByRole("row", { name: /pending/ });
    expect(pending.textContent).toMatch(/pending\s*2\s*503\s*1\s*status 503/);
    const failed = table.getByRole("row", { name: /failed/ });
    expect(failed.textContent).toMatch(/failed\s*5\s*—\s*3\s*connection refused/);
  });
});
