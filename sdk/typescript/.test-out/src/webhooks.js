export const SIGNATURE_HEADER = "X-CrawlerAI-Signature";
const encoder = new TextEncoder();
async function hmac(secret, body) {
    const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
        "sign",
    ]);
    const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, body));
    return Array.from(mac, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
function bytesOf(body) {
    return typeof body === "string" ? encoder.encode(body) : body;
}
/** The signature header's value for `body`. */
export async function signWebhook(secret, body) {
    return `sha256=${await hmac(secret, bytesOf(body))}`;
}
/** Whether `signature` (the header's value) is `body`'s, compared in constant time. `body` is the raw request body:
 * parse it only after this passes. */
export async function verifyWebhook(secret, body, signature) {
    if (signature === null || signature === undefined)
        return false;
    const expected = encoder.encode(await signWebhook(secret, body));
    const given = encoder.encode(signature);
    if (expected.length !== given.length)
        return false;
    let difference = 0;
    for (const [index, byte] of expected.entries())
        difference |= byte ^ (given[index] ?? 0);
    return difference === 0;
}
/** The job summary a verified webhook carries; throws for a body not signed with `secret`. */
export async function parseWebhook(secret, body, signature) {
    if (!(await verifyWebhook(secret, body, signature)))
        throw new Error("the webhook's signature does not match its body");
    const text = typeof body === "string" ? body : new TextDecoder().decode(body);
    return JSON.parse(text);
}
