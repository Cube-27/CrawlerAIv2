import assert from "node:assert/strict";
import { test } from "node:test";
import { APIError, CrawlerAI, JobTimeout, parseEvents, signWebhook, verifyWebhook, parseWebhook } from "../src/index.js";
const JOB = "0192a000-0000-7000-8000-0000000000aa";
function api(reply) {
    const seen = [];
    const fake = (input, init) => {
        const request = {
            method: init?.method ?? "GET",
            url: String(input),
            headers: new Headers(init?.headers),
            body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
        };
        seen.push(request);
        return Promise.resolve(reply(request));
    };
    return { client: new CrawlerAI("key-1", { baseUrl: "https://api.example.test/", fetch: fake }), seen };
}
const summary = (status) => ({ id: JOB, kind: "crawl", status });
test("a crawl sends exactly the members given, with the bearer key", async () => {
    const { client, seen } = api(() => Response.json({ job_id: JOB }, { status: 202 }));
    const submitted = await client.crawl({
        url: "https://docs.example.test/",
        formats: ["markdown"],
        strategy: "best_first",
        query: "rate limits",
    });
    assert.equal(submitted.job_id, JOB);
    assert.equal(seen[0]?.url, "https://api.example.test/v1/crawl");
    assert.equal(seen[0]?.headers.get("authorization"), "Bearer key-1");
    assert.deepEqual(seen[0]?.body, {
        url: "https://docs.example.test/",
        formats: ["markdown"],
        strategy: "best_first",
        query: "rate limits",
    });
});
test("a problem is an APIError with its status and type", async () => {
    const { client } = api(() => Response.json({ type: "search_unavailable", title: "Search unavailable", detail: "no provider" }, { status: 503 }));
    await assert.rejects(client.search({ query: "kettles" }), (error) => {
        assert.ok(error instanceof APIError);
        assert.equal(error.status, 503);
        assert.equal(error.type, "search_unavailable");
        return true;
    });
});
test("search with scrape returns the results and the job", async () => {
    const answer = { query: "kettles", results: [{ position: 1, url: "https://a.example.test/", title: "A", snippet: "" }], job_id: JOB, skipped: 0 };
    const { client, seen } = api(() => Response.json(answer));
    const result = await client.search({ query: "kettles", limit: 1, scrape: { formats: ["markdown"] } });
    assert.deepEqual(seen[0]?.body, { query: "kettles", limit: 1, scrape: { formats: ["markdown"] } });
    assert.equal(result.results[0]?.url, "https://a.example.test/");
    assert.equal(result.job_id, JOB);
});
test("waitForJob polls until the job ends, and times out", async () => {
    const statuses = ["queued", "running", "completed"];
    const polled = api(() => Response.json(summary(statuses.shift() ?? "completed")));
    assert.equal((await polled.client.waitForJob(JOB, { pollIntervalS: 0 })).status, "completed");
    const stuck = api(() => Response.json(summary("running")));
    await assert.rejects(stuck.client.waitForJob(JOB, { pollIntervalS: 0.01, timeoutS: 0.05 }), JobTimeout);
});
test("job results are paged through their cursor", async () => {
    const pages = {
        "": { items: [{ n: 1 }, { n: 2 }], next_cursor: "c2" },
        c2: { items: [{ n: 3 }], next_cursor: null },
    };
    const { client, seen } = api((request) => Response.json(pages[new URL(request.url).searchParams.get("cursor") ?? ""]));
    const items = [];
    for await (const item of client.iterJobResults(JOB, 2))
        items.push(item);
    assert.deepEqual(items, [{ n: 1 }, { n: 2 }, { n: 3 }]);
    assert.deepEqual(seen.map((request) => new URL(request.url).search), ["?format=json&limit=2", "?format=json&cursor=c2&limit=2"]);
});
const STREAM = ': keep-alive\n\nid: 4\nevent: progress\ndata: {"done": 1}\n\nid: 5\nevent: completed\ndata: {"status":\ndata: "completed"}\n\n';
test("events parse ids, kinds and multi-line data, whatever the chunking", async () => {
    const bytes = new TextEncoder().encode(STREAM);
    const { client, seen } = api(() => {
        const body = new ReadableStream({
            start(controller) {
                for (let i = 0; i < bytes.length; i += 7)
                    controller.enqueue(bytes.slice(i, i + 7));
                controller.close();
            },
        });
        return new Response(body, { headers: { "content-type": "text/event-stream" } });
    });
    const events = [];
    for await (const event of client.events(JOB, "3"))
        events.push(event);
    assert.equal(seen[0]?.headers.get("last-event-id"), "3");
    assert.deepEqual(events, [
        { kind: "progress", id: "4", data: { done: 1 } },
        { kind: "completed", id: "5", data: { status: "completed" } },
    ]);
});
test("a CRLF split between two chunks is one line break", async () => {
    const chunks = ["id: 1\r", "\nevent: progress\r\ndata: {}\r", "\n\r\n"];
    const body = new ReadableStream({
        start(controller) {
            for (const chunk of chunks)
                controller.enqueue(new TextEncoder().encode(chunk));
            controller.close();
        },
    });
    const events = [];
    for await (const event of parseEvents(body))
        events.push(event);
    assert.deepEqual(events, [{ kind: "progress", id: "1", data: {} }]);
});
test("parseEvents alone reads a stream that ends without a blank line", async () => {
    const body = new Response('event: progress\ndata: {"a":1}').body;
    assert.ok(body !== null);
    const events = [];
    for await (const event of parseEvents(body))
        events.push(event);
    assert.deepEqual(events, [{ kind: "progress", id: null, data: { a: 1 } }]);
});
test("a webhook is verified with the secret and the exact body", async () => {
    const body = JSON.stringify(summary("completed"));
    const signature = await signWebhook("s3cret", body);
    assert.match(signature, /^sha256=[0-9a-f]{64}$/);
    assert.equal(await verifyWebhook("s3cret", body, signature), true);
    assert.equal(await verifyWebhook("other", body, signature), false);
    assert.equal(await verifyWebhook("s3cret", `${body} `, signature), false);
    assert.equal(await verifyWebhook("s3cret", body, null), false);
    assert.equal((await parseWebhook("s3cret", body, signature)).status, "completed");
    await assert.rejects(parseWebhook("other", body, signature), /signature/);
});
test("the Python SDK and this one sign alike: HMAC-SHA256 of the body", async () => {
    // RFC 4231 test case 2: key "Jefe", data "what do ya want for nothing?".
    assert.equal(await signWebhook("Jefe", "what do ya want for nothing?"), "sha256=5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");
});
