/** Verifying a completion webhook: `X-CrawlerAI-Signature: sha256=<hex>`, the HMAC-SHA256 (RFC 2104) of the request
 * body keyed with the UTF-8 bytes of the API key's webhook secret. Uses Web Crypto, so it runs in Node, Deno, Bun,
 * browsers and edge runtimes. */
import type { components } from "./schema.js";
export declare const SIGNATURE_HEADER = "X-CrawlerAI-Signature";
/** The signature header's value for `body`. */
export declare function signWebhook(secret: string, body: string | Uint8Array): Promise<string>;
/** Whether `signature` (the header's value) is `body`'s, compared in constant time. `body` is the raw request body:
 * parse it only after this passes. */
export declare function verifyWebhook(secret: string, body: string | Uint8Array, signature: string | null | undefined): Promise<boolean>;
/** The job summary a verified webhook carries; throws for a body not signed with `secret`. */
export declare function parseWebhook(secret: string, body: string | Uint8Array, signature: string | null | undefined): Promise<components["schemas"]["JobSummary"]>;
