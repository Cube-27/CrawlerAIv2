import type { CacheMode, FetchMember, MethodHint, PageAction } from "../../api/scrape";
import { optionalNumber } from "./pageRequest";
import { member, text, type StoredRequest } from "./run/storedRequest";

/** The Advanced options every page request shares (D-1430, D-1436): the caller's headers and cookies, a proxy pool,
 * what the browser waits for, the cache mode and the page actions, as the `fetch` members they become. */

/** What a page step does, and how each kind names what it acts on. */
export type ActionType = PageAction["type"];
export type ActionMode =
  | "ms"
  | "selector"
  | "network_idle"
  | "text"
  | "bottom"
  | "by"
  | "stable"
  | "key";

/** One row of the actions editor: its kind, how it names its target (`mode`), the target or amount (`value`) and, for
 * a `type` step, the text typed. `key` keeps a row's identity while rows move. */
export interface ActionRow {
  key: string;
  type: ActionType;
  mode: ActionMode;
  value: string;
  text: string;
}

/** The modes each kind of step offers, the first being the one a new row starts with. */
export const ACTION_MODES: Readonly<Record<ActionType, readonly ActionMode[]>> = {
  wait: ["ms", "selector", "network_idle"],
  click: ["selector", "text"],
  scroll: ["bottom", "by", "stable"],
  press: ["key"],
  type: ["selector"],
};

/** The server's cap on steps (`config_ir.page_actions.MAX_ACTIONS`). */
export const MAX_ACTIONS = 20;

export interface AdvancedFetch {
  /** One `Name: value` per line. */
  headers: string;
  /** One `name=value` per line, or several separated by `;` as a Cookie header writes them. */
  cookies: string;
  proxyPool: string;
  /** Milliseconds, `network_idle` or a CSS selector; empty for none. */
  waitFor: string;
  cache: CacheMode;
  actions: readonly ActionRow[];
}

export const DEFAULT_ADVANCED: AdvancedFetch = {
  headers: "",
  cookies: "",
  proxyPool: "",
  waitFor: "",
  cache: "default",
  actions: [],
};

/** A new row of `type`, in its first mode. */
export function newAction(type: ActionType): ActionRow {
  return {
    key: crypto.randomUUID(),
    type,
    mode: ACTION_MODES[type][0] ?? "selector",
    value: "",
    text: "",
  };
}

/** `Name: value` lines (RFC 9110 §5.1 field lines) or `name=value` pairs as a map; a line without the separator is
 * left out. */
export function pairs(textValue: string, separator: ":" | "="): Record<string, string> {
  const entries = separator === "=" ? textValue.split(/[\n;]/) : textValue.split("\n");
  const map: Record<string, string> = {};
  for (const entry of entries) {
    const at = entry.indexOf(separator);
    const name = at < 0 ? "" : entry.slice(0, at).trim();
    if (name !== "") map[name] = entry.slice(at + 1).trim();
  }
  return map;
}

/** `wait_for` as the server takes it: a whole number of milliseconds, or the text itself. */
export function waitFor(value: string): number | string | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  return /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed;
}

/** The step a row stands for; null while the row lacks what its mode needs (it is not sent). */
export function toAction(row: ActionRow): PageAction | null {
  const value = row.value.trim();
  const amount = Number(value);
  switch (row.mode) {
    case "network_idle":
      return { type: "wait", network_idle: true };
    case "bottom":
      return { type: "scroll", to: "bottom" };
    case "stable":
      return { type: "scroll", until: "stable" };
    default:
      break;
  }
  if (value === "") return null;
  switch (row.mode) {
    case "ms":
      return Number.isInteger(amount) && amount > 0 ? { type: "wait", ms: amount } : null;
    case "by":
      return Number.isInteger(amount) ? { type: "scroll", by: amount } : null;
    case "key":
      return { type: "press", key: value };
    case "text":
      return { type: "click", text: value };
    default:
      return selectorAction(row.type, value, row.text);
  }
}

function selectorAction(type: ActionType, selector: string, typed: string): PageAction | null {
  if (type === "wait") return { type: "wait", selector };
  if (type === "click") return { type: "click", selector };
  if (type === "type") return { type: "type", selector, text: typed };
  return null;
}

/** The request's `fetch` member: the method hint, `max_rows` while filled, and each Advanced setting while it is set,
 * so an untouched form sends what it sent before. */
export function fetchMember(
  methodHint: MethodHint,
  maxRows: number,
  advanced: AdvancedFetch = DEFAULT_ADVANCED,
): FetchMember {
  const headers = pairs(advanced.headers, ":");
  const cookies = pairs(advanced.cookies, "=");
  const wait = waitFor(advanced.waitFor);
  const actions = advanced.actions.map(toAction).filter((action) => action !== null);
  const proxyPool = advanced.proxyPool.trim();
  return {
    method_hint: methodHint,
    ...optionalNumber("max_rows", maxRows),
    ...(Object.keys(headers).length === 0 ? {} : { headers }),
    ...(Object.keys(cookies).length === 0 ? {} : { cookies }),
    ...(proxyPool === "" ? {} : { proxy_pool: proxyPool }),
    ...(wait === null ? {} : { wait_for: wait }),
    ...(actions.length === 0 ? {} : { actions }),
    ...(advanced.cache === "default" ? {} : { cache: advanced.cache }),
  };
}

const CACHE_MODES: readonly CacheMode[] = ["default", "bypass", "only"];

/** The Advanced settings of a stored request. Header and cookie values come back redacted (D-1432), so they are not
 * shown again: a re-run sends none until they are entered anew. */
export function storedAdvanced(request: StoredRequest): AdvancedFetch {
  const fetch = member(request, "fetch");
  const wait = fetch["wait_for"];
  const actions = Array.isArray(fetch["actions"]) ? fetch["actions"] : [];
  return {
    ...DEFAULT_ADVANCED,
    proxyPool: text(fetch, "proxy_pool"),
    waitFor: storedWaitFor(wait),
    cache: CACHE_MODES.find((mode) => mode === fetch["cache"]) ?? "default",
    actions: actions.map(storedAction).filter((row) => row !== null),
  };
}

function storedWaitFor(wait: unknown): string {
  if (typeof wait === "number") return String(wait);
  return typeof wait === "string" ? wait : "";
}

/** A stored number member as the value field shows it; "" when it is not a number. */
function numberText(value: unknown): string {
  return typeof value === "number" ? String(value) : "";
}

function storedAction(stored: unknown): ActionRow | null {
  if (typeof stored !== "object" || stored === null) return null;
  const action = stored as StoredRequest;
  const row = (type: ActionType, mode: ActionMode, value = "", typed = ""): ActionRow => ({
    key: crypto.randomUUID(),
    type,
    mode,
    value,
    text: typed,
  });
  const selector = text(action, "selector");
  switch (action["type"]) {
    case "wait":
      if (action["network_idle"] === true) return row("wait", "network_idle");
      return selector === ""
        ? row("wait", "ms", numberText(action["ms"]))
        : row("wait", "selector", selector);
    case "click":
      return selector === ""
        ? row("click", "text", text(action, "text"))
        : row("click", "selector", selector);
    case "scroll":
      if (typeof action["by"] === "number") return row("scroll", "by", String(action["by"]));
      return row("scroll", action["until"] === "stable" ? "stable" : "bottom");
    case "press":
      return row("press", "key", text(action, "key"));
    case "type":
      return row("type", "selector", selector, text(action, "text"));
    default:
      return null;
  }
}
