import { describe, expect, it } from "vite-plus/test";
import { fetchMember, newAction, pairs, storedAdvanced, toAction, waitFor } from "./advanced";

// The Advanced settings as `fetch` members, and back from a stored request.

describe("advanced fetch settings", () => {
  it("reads header lines and cookie pairs, leaving out a line without its separator", () => {
    expect(pairs("Authorization: Bearer a:b\nnot a header\nX-Key:  v ", ":")).toEqual({
      Authorization: "Bearer a:b",
      "X-Key": "v",
    });
    expect(pairs("sid=a=b; theme=dark\nlang=de", "=")).toEqual({
      sid: "a=b",
      theme: "dark",
      lang: "de",
    });
  });

  it("sends wait for as milliseconds when it is a whole number, else as written", () => {
    expect(waitFor(" 1500 ")).toBe(1500);
    expect(waitFor("network_idle")).toBe("network_idle");
    expect(waitFor(".price")).toBe(".price");
    expect(waitFor("  ")).toBeNull();
  });

  it("turns each row into its step, and a row missing its value into none", () => {
    const row = (type: Parameters<typeof newAction>[0], mode: string, value = "", text = "") => ({
      ...newAction(type),
      mode: mode as ReturnType<typeof newAction>["mode"],
      value,
      text,
    });
    expect(toAction(row("wait", "ms", "800"))).toEqual({ type: "wait", ms: 800 });
    expect(toAction(row("wait", "ms", "0.5"))).toBeNull();
    expect(toAction(row("wait", "network_idle"))).toEqual({ type: "wait", network_idle: true });
    expect(toAction(row("click", "text", "Show more"))).toEqual({
      type: "click",
      text: "Show more",
    });
    expect(toAction(row("click", "selector", ""))).toBeNull();
    expect(toAction(row("scroll", "by", "-300"))).toEqual({ type: "scroll", by: -300 });
    expect(toAction(row("scroll", "stable"))).toEqual({ type: "scroll", until: "stable" });
    expect(toAction(row("press", "key", "Enter"))).toEqual({ type: "press", key: "Enter" });
    expect(toAction(row("type", "selector", "#q", "lamp"))).toEqual({
      type: "type",
      selector: "#q",
      text: "lamp",
    });
  });

  it("shows a stored request's settings again, without the redacted header and cookie values", () => {
    const stored = storedAdvanced({
      fetch: {
        headers: { Authorization: "**********" },
        cookies: { sid: "**********" },
        proxy_pool: "eu",
        wait_for: 2000,
        cache: "only",
        actions: [
          { type: "click", text: "More", selector: null },
          { type: "scroll", until: "stable" },
          { type: "type", selector: "#q", text: "lamp" },
        ],
      },
    });

    expect(fetchMember("browser", Number.NaN, stored)).toEqual({
      method_hint: "browser",
      proxy_pool: "eu",
      wait_for: 2000,
      cache: "only",
      actions: [
        { type: "click", text: "More" },
        { type: "scroll", until: "stable" },
        { type: "type", selector: "#q", text: "lamp" },
      ],
    });
  });
});
