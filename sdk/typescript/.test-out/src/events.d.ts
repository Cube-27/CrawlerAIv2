/** Server-sent events (WHATWG HTML §9.2.5) as the job events endpoint sends them. */
/** One event: `kind` is the event name (`progress`, `completed`, ...), `id` the id to resume after, `data` the decoded
 * JSON payload (the raw text when it is not JSON). */
export interface JobEvent {
    kind: string;
    id: string | null;
    data: unknown;
}
/** The events of a response body, as they arrive. */
export declare function parseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<JobEvent>;
