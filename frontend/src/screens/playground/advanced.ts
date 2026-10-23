import type {
  CacheMode,
  FetchMember,
  MethodHint,
  PageAction,
  ScreenshotArea,
} from "../../api/scrape";
import { LIMITS } from "../../api/limits";
import type { StoredRequestOf } from "../../api/jobs";
import { optionalNumber } from "./pageRequest";

/** The Advanced options every page request shares: the caller's headers and cookies, a proxy pool,
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

/** The server's cap on steps. */
export const MAX_ACTIONS = LIMITS["FetchOptions-Input"].actions.maxItems;

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
 * so an untouched form sends what it sent before; `area` is the `screenshot` area when a screenshot is asked for. */
export function fetchMember(
  methodHint: MethodHint,
  maxRows: number,
  advanced: AdvancedFetch = DEFAULT_ADVANCED,
  area?: ScreenshotArea,
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
    ...(area === undefined ? {} : { screenshot: area }),
  };
}

/** The page steps that make a fetch run in the browser: `wait_for` or any action (the server's `in_browser` property of the fetch options). */
function hasBrowserSteps(fetch: FetchMember): boolean {
  return fetch.wait_for !== undefined || (fetch.actions?.length ?? 0) > 0;
}

/** The formats only a browser makes (`CAPTURE_FORMATS` of the server). */
const CAPTURE_FORMATS: ReadonlySet<string> = new Set(["screenshot", "pdf"]);
const CAPTURE_OVER_HTTP = {
  "fetch.method_hint": "Screenshots and PDFs are made in the browser: choose Auto or Browser.",
};
const STEPS_OVER_HTTP = {
  "fetch.method_hint": "Wait for and page actions run in the browser: choose Auto or Browser.",
};
const HEADERS_IN_BROWSER = {
  "fetch.headers":
    "Headers are sent over HTTP only: remove them, or use neither the Browser method, wait for nor page actions.",
};

function methodHintError(
  fetch: FetchMember,
  formats: readonly string[],
): Readonly<Record<string, string>> | null {
  if (fetch.method_hint !== "http") return null;
  if (formats.some((format) => CAPTURE_FORMATS.has(format))) return CAPTURE_OVER_HTTP;
  return hasBrowserSteps(fetch) ? STEPS_OVER_HTTP : null;
}

function headersError(fetch: FetchMember): Readonly<Record<string, string>> | null {
  const inBrowser = fetch.method_hint === "browser" || hasBrowserSteps(fetch);
  return fetch.headers !== undefined && inBrowser ? HEADERS_IN_BROWSER : null;
}

/** `errors` with the `fetch` member's own after them; `errors` itself when it has none. The server always refuses
 * these combinations (`FetchOptions._coherent`, `check_formats`): a screenshot, a PDF, `wait_for` or actions need the
 * browser, so not the `http` method; headers go over HTTP only, so not with the browser. */
export function withFetchErrors(
  errors: Readonly<Record<string, string>>,
  fetch: FetchMember,
  formats: readonly string[],
): Readonly<Record<string, string>> {
  const method = methodHintError(fetch, formats);
  const headers = headersError(fetch);
  return method === null && headers === null ? errors : { ...errors, ...method, ...headers };
}

type StoredFetch = StoredRequestOf<"scrape">["fetch"];
type StoredAction = StoredFetch["actions"][number];

/** The Advanced settings of a stored request's `fetch`. Header and cookie values come back redacted, so they are not
 * shown again: a re-run sends none until they are entered anew. */
export function storedAdvanced(fetch: StoredFetch): AdvancedFetch {
  return {
    ...DEFAULT_ADVANCED,
    proxyPool: fetch.proxy_pool ?? "",
    waitFor: fetch.wait_for === null ? "" : String(fetch.wait_for),
    cache: fetch.cache,
    actions: fetch.actions.map(storedAction),
  };
}

function row(type: ActionType, mode: ActionMode, value = "", typed = ""): ActionRow {
  return { key: crypto.randomUUID(), type, mode, value, text: typed };
}

function storedWait(action: Extract<StoredAction, { type: "wait" }>): ActionRow {
  if (action.network_idle) return row("wait", "network_idle");
  return action.selector === null
    ? row("wait", "ms", action.ms === null ? "" : String(action.ms))
    : row("wait", "selector", action.selector);
}

/** A stored step as the actions editor shows it; a step on an `xpath` shows as the selector modes do. */
function storedAction(action: StoredAction): ActionRow {
  switch (action.type) {
    case "wait":
      return storedWait(action);
    case "click":
      return action.selector === null
        ? row("click", "text", action.text ?? "")
        : row("click", "selector", action.selector);
    case "scroll":
      if (action.by !== null) return row("scroll", "by", String(action.by));
      return row("scroll", action.until === "stable" ? "stable" : "bottom");
    case "press":
      return row("press", "key", action.key);
    case "type":
      return row("type", "selector", action.selector ?? "", action.text);
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}
