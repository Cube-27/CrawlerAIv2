import { parseEvents } from "./events.js";
export { parseEvents } from "./events.js";
export { signWebhook, verifyWebhook, parseWebhook, SIGNATURE_HEADER } from "./webhooks.js";
/** `url` without the slashes that end it. */
function trimSlashes(url) {
    let end = url.length;
    while (end > 0 && url[end - 1] === "/")
        end -= 1;
    return url.slice(0, end);
}
const ENDED = new Set(["completed", "failed", "cancelled"]);
/** The API answered with a problem document (RFC 9457): `type` is its code (`validation`, `search_unavailable`, ...). */
export class APIError extends Error {
    status;
    problem;
    constructor(status, problem) {
        super(`${String(status)} ${problem.type ?? "error"}: ${problem.detail ?? problem.title ?? ""}`);
        this.name = "APIError";
        this.status = status;
        this.problem = problem;
    }
    get type() {
        return this.problem.type ?? "error";
    }
}
/** `waitForJob` gave up before the job ended. */
export class JobTimeout extends Error {
    jobId;
    constructor(jobId, seconds) {
        super(`job ${jobId} did not end within ${String(seconds)} s`);
        this.jobId = jobId;
        this.name = "JobTimeout";
    }
}
/** The client. Each request method sends exactly the members given, so the server's defaults apply to the rest. */
export class CrawlerAI {
    #base;
    #key;
    #fetch;
    constructor(apiKey, options = {}) {
        this.#key = apiKey;
        this.#base = trimSlashes(options.baseUrl ?? "http://localhost:8000");
        this.#fetch = options.fetch ?? ((...args) => fetch(...args));
    }
    async #send(method, path, init = {}) {
        const query = init.query === undefined ? "" : `?${new URLSearchParams(init.query).toString()}`;
        const headers = {
            Authorization: `Bearer ${this.#key}`,
            Accept: init.accept ?? "application/json",
            ...init.headers,
        };
        if (init.body !== undefined)
            headers["Content-Type"] = "application/json";
        const response = await this.#fetch(`${this.#base}${path}${query}`, {
            method,
            headers,
            ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
        });
        if (!response.ok) {
            const problem = (await response.json().catch(() => ({})));
            throw new APIError(response.status, problem);
        }
        return response;
    }
    async #json(method, path, body, query) {
        const response = await this.#send(method, path, {
            ...(body === undefined ? {} : { body }),
            ...(query === undefined ? {} : { query }),
        });
        return (await response.json());
    }
    /** `POST /v1/scrape`: one page, fetched while you wait. */
    scrape(request) {
        return this.#json("POST", "/v1/scrape", request);
    }
    /** `POST /v1/map`: the URLs of a site. */
    map(request) {
        return this.#json("POST", "/v1/map", request);
    }
    /** `POST /v1/search`: web results; `scrape` scrapes them in a batch job (`job_id` of the answer). Rejects with an
     * `APIError` of type `search_unavailable` (503) when the operator has configured no search provider. */
    search(request) {
        return this.#json("POST", "/v1/search", request);
    }
    /** `POST /v1/crawl`: queue a crawl; `strategy: "best_first"` with a `query` fetches the best-matching pages first. */
    crawl(request) {
        return this.#json("POST", "/v1/crawl", request);
    }
    /** `POST /v1/batch/scrape`: queue a scrape of many URLs. */
    batchScrape(request) {
        return this.#json("POST", "/v1/batch/scrape", request);
    }
    /** `POST /v1/extract`: queue the extraction of a record from each URL. */
    extract(request) {
        return this.#json("POST", "/v1/extract", request);
    }
    /** `GET /v1/jobs/{id}`. */
    job(jobId) {
        return this.#json("GET", `/v1/jobs/${jobId}`);
    }
    /** `DELETE /v1/jobs/{id}`: ask the job to stop. */
    cancelJob(jobId) {
        return this.#json("DELETE", `/v1/jobs/${jobId}`);
    }
    /** One page of `GET /v1/jobs/{id}/results`. */
    jobResults(jobId, page = {}) {
        const query = { format: "json" };
        if (page.cursor !== undefined)
            query["cursor"] = page.cursor;
        if (page.limit !== undefined)
            query["limit"] = String(page.limit);
        return this.#json("GET", `/v1/jobs/${jobId}/results`, undefined, query);
    }
    /** Every result of the job, page after page. */
    async *iterJobResults(jobId, pageSize) {
        let cursor;
        for (;;) {
            const page = await this.jobResults(jobId, {
                ...(cursor === undefined ? {} : { cursor }),
                ...(pageSize === undefined ? {} : { limit: pageSize }),
            });
            yield* page.items;
            if (page.next_cursor === null)
                return;
            cursor = page.next_cursor;
        }
    }
    /** Poll the job until it is `completed`, `failed` or `cancelled`, and return its summary. Rejects with `JobTimeout`
     * after `timeoutS` seconds (never, when absent). */
    waitForJob(jobId, options = {}) {
        const deadline = options.timeoutS === undefined ? Infinity : Date.now() + options.timeoutS * 1000;
        return this.#poll(jobId, (options.pollIntervalS ?? 1) * 1000, deadline, options.timeoutS ?? 0);
    }
    async #poll(jobId, intervalMs, deadline, timeoutS) {
        const summary = await this.job(jobId);
        if (ENDED.has(summary.status))
            return summary;
        if (Date.now() >= deadline)
            throw new JobTimeout(jobId, timeoutS);
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
        return this.#poll(jobId, intervalMs, deadline, timeoutS);
    }
    /** The job's run events live (`GET /v1/jobs/{id}/events`), until its end event; resume with the last id seen. */
    async *events(jobId, lastEventId) {
        const response = await this.#send("GET", `/v1/jobs/${jobId}/events`, {
            accept: "text/event-stream",
            ...(lastEventId === undefined ? {} : { headers: { "Last-Event-ID": lastEventId } }),
        });
        if (response.body === null)
            return;
        yield* parseEvents(response.body);
    }
}
