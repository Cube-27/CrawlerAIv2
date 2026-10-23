import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite-plus";

// The dev server attaches the UI's API key to proxied requests, so the browser never holds one. Vite
// reads no repo-root `.env` by itself, so it is loaded from `..`: pnpm runs scripts in this package's directory. The
// variable has no `VITE_` prefix, so it never reaches client code. An empty value counts as unset (.env.example).
const uiApiKey = loadEnv("development", "..", "")["CRAWLERAI_UI_API_KEY"];
const target = "http://127.0.0.1:8000";

// W3C Fetch Metadata: a browser marks each request with where it came from (`Sec-Fetch-Site`). The proxy attaches the
// key, so a request another site's page made (`cross-site`, `same-site`) is refused, not proxied: Vite answers 404.
// `same-origin` is the app's own, `none` one the user typed; a request with no such header is not from a browser page
// (curl, scripts) and passes.
const OWN_SITE: ReadonlySet<string> = new Set(["same-origin", "none"]);

/** The proxy's `bypass`: `false` refuses the request, `undefined` proxies it. Node's request headers, typed here as
 * this file needs them (the frontend has no Node types). */
export function refuseCrossSite(req: {
  headers: Readonly<Record<string, string | string[] | undefined>>;
}): false | undefined {
  const site = req.headers["sec-fetch-site"];
  return site === undefined || (typeof site === "string" && OWN_SITE.has(site)) ? undefined : false;
}

const backend: ProxyOptions =
  uiApiKey === undefined || uiApiKey === ""
    ? { target, bypass: refuseCrossSite }
    : { target, bypass: refuseCrossSite, headers: { Authorization: `Bearer ${uiApiKey}` } };

export default defineConfig({
  // `vp migrate` translated the former ESLint sets rule by rule: typescript-eslint strictTypeChecked, react-hooks
  // recommended (`react/*`) and jsx-a11y strict. Without an Oxlint equivalent: react-hooks/config and gating (no
  // React Compiler options) and @typescript-eslint/no-unsafe-enum-assignment; strict mode covers no-dupe-args and
  // no-octal.
  lint: {
    plugins: ["oxc", "typescript", "unicorn"],
    categories: {
      correctness: "warn",
    },
    options: {
      typeAware: true,
      typeCheck: true,
    },
    overrides: [
      {
        files: ["**/*.{ts,tsx}"],
        rules: {
          "constructor-super": "off",
          "for-direction": "error",
          "getter-return": "off",
          "no-async-promise-executor": "error",
          "no-case-declarations": "error",
          "no-class-assign": "off",
          "no-compare-neg-zero": "error",
          "no-cond-assign": "error",
          "no-const-assign": "off",
          "no-constant-binary-expression": "error",
          "no-constant-condition": "error",
          "no-control-regex": "error",
          "no-debugger": "error",
          "no-delete-var": "error",
          "no-dupe-class-members": "off",
          "no-dupe-else-if": "error",
          "no-dupe-keys": "off",
          "no-duplicate-case": "error",
          "no-empty": "error",
          "no-empty-character-class": "error",
          "no-empty-pattern": "error",
          "no-empty-static-block": "error",
          "no-ex-assign": "error",
          "no-extra-boolean-cast": "error",
          "no-fallthrough": "error",
          "no-func-assign": "off",
          "no-global-assign": "error",
          "no-import-assign": "off",
          "no-invalid-regexp": "error",
          "no-irregular-whitespace": "error",
          "no-loss-of-precision": "error",
          "no-misleading-character-class": "error",
          "no-new-native-nonconstructor": "off",
          "no-nonoctal-decimal-escape": "error",
          "no-obj-calls": "off",
          "no-prototype-builtins": "error",
          "no-regex-spaces": "error",
          "no-self-assign": "error",
          "no-setter-return": "off",
          "no-shadow-restricted-names": "error",
          "no-sparse-arrays": "error",
          "no-this-before-super": "off",
          "no-unexpected-multiline": "error",
          "no-unreachable": "off",
          "no-unsafe-finally": "error",
          "no-unsafe-negation": "off",
          "no-unsafe-optional-chaining": "error",
          "no-unused-labels": "error",
          "no-unused-private-class-members": "error",
          "no-unused-vars": "error",
          "no-useless-backreference": "error",
          "no-useless-catch": "error",
          "no-useless-escape": "error",
          "no-with": "off",
          "require-yield": "error",
          "use-isnan": "error",
          "valid-typeof": "error",
          "no-var": "error",
          "prefer-const": "error",
          "prefer-rest-params": "error",
          "prefer-spread": "error",
          "no-array-constructor": "error",
          "no-unused-expressions": "error",
          "no-useless-constructor": "error",
          "typescript/await-thenable": "error",
          "typescript/ban-ts-comment": [
            "error",
            {
              minimumDescriptionLength: 10,
            },
          ],
          "typescript/no-array-delete": "error",
          "typescript/no-base-to-string": "error",
          "typescript/no-confusing-void-expression": "error",
          "typescript/no-deprecated": "error",
          "typescript/no-duplicate-enum-values": "error",
          "typescript/no-duplicate-type-constituents": "error",
          "typescript/no-dynamic-delete": "error",
          "typescript/no-empty-object-type": "error",
          "typescript/no-explicit-any": "error",
          "typescript/no-extra-non-null-assertion": "error",
          "typescript/no-extraneous-class": "error",
          "typescript/no-floating-promises": "error",
          "typescript/no-for-in-array": "error",
          "typescript/no-generated-empty-object-type": "error",
          "typescript/no-implied-eval": "error",
          "typescript/no-invalid-void-type": "error",
          "typescript/no-meaningless-void-operator": "error",
          "typescript/no-misused-new": "error",
          "typescript/no-misused-promises": "error",
          "typescript/no-misused-spread": "error",
          "typescript/no-mixed-enums": "error",
          "typescript/no-namespace": "error",
          "typescript/no-non-null-asserted-nullish-coalescing": "error",
          "typescript/no-non-null-asserted-optional-chain": "error",
          "typescript/no-non-null-assertion": "error",
          "typescript/no-redundant-type-constituents": "error",
          "typescript/no-require-imports": "error",
          "typescript/no-this-alias": "error",
          "typescript/no-unnecessary-boolean-literal-compare": "error",
          "typescript/no-unnecessary-condition": "error",
          "typescript/no-unnecessary-template-expression": "error",
          "typescript/no-unnecessary-type-arguments": "error",
          "typescript/no-unnecessary-type-assertion": "error",
          "typescript/no-unnecessary-type-constraint": "error",
          "typescript/no-unnecessary-type-conversion": "error",
          "typescript/no-unnecessary-type-parameters": "error",
          "typescript/no-unsafe-argument": "error",
          "typescript/no-unsafe-assignment": "error",
          "typescript/no-unsafe-call": "error",
          "typescript/no-unsafe-declaration-merging": "error",
          "typescript/no-unsafe-enum-comparison": "error",
          "typescript/no-unsafe-function-type": "error",
          "typescript/no-unsafe-member-access": "error",
          "typescript/no-unsafe-return": "error",
          "typescript/no-unsafe-unary-minus": "error",
          "typescript/no-useless-default-assignment": "error",
          "typescript/no-wrapper-object-types": "error",
          "typescript/only-throw-error": "error",
          "typescript/prefer-as-const": "error",
          "typescript/prefer-literal-enum-member": "error",
          "typescript/prefer-namespace-keyword": "error",
          "typescript/prefer-promise-reject-errors": "error",
          "typescript/prefer-reduce-type-parameter": "error",
          "typescript/prefer-return-this-type": "error",
          "typescript/related-getter-setter-pairs": "error",
          "typescript/require-await": "error",
          "typescript/restrict-plus-operands": [
            "error",
            {
              allowAny: false,
              allowBoolean: false,
              allowNullish: false,
              allowNumberAndString: false,
              allowRegExp: false,
            },
          ],
          "typescript/restrict-template-expressions": [
            "error",
            {
              allowAny: false,
              allowBoolean: false,
              allowNever: false,
              allowNullish: false,
              allowNumber: false,
              allowRegExp: false,
            },
          ],
          "typescript/return-await": ["error", "error-handling-correctness-only"],
          "typescript/triple-slash-reference": "error",
          "typescript/unbound-method": "error",
          "typescript/unified-signatures": "error",
          "typescript/use-unknown-in-catch-callback-variable": "error",
          "react/rules-of-hooks": "error",
          // SonarCloud S6479: list keys by a stable id, never the array index.
          "react/no-array-index-key": "error",
          "react/exhaustive-deps": "warn",
          "react/static-components": "error",
          "react/use-memo": "error",
          "react/preserve-manual-memoization": "error",
          "react/incompatible-library": "warn",
          "react/immutability": "error",
          "react/globals": "error",
          "react/refs": "error",
          "react/set-state-in-effect": "error",
          "react/error-boundaries": "error",
          "react/purity": "error",
          "react/set-state-in-render": "error",
          "react/unsupported-syntax": "warn",
          "jsx-a11y/alt-text": "error",
          "jsx-a11y/anchor-has-content": "error",
          "jsx-a11y/anchor-is-valid": "error",
          "jsx-a11y/aria-activedescendant-has-tabindex": "error",
          "jsx-a11y/aria-props": "error",
          "jsx-a11y/aria-proptypes": "error",
          "jsx-a11y/aria-role": "error",
          "jsx-a11y/aria-unsupported-elements": "error",
          "jsx-a11y/autocomplete-valid": "error",
          "jsx-a11y/click-events-have-key-events": "error",
          "jsx-a11y/control-has-associated-label": "off",
          "jsx-a11y/heading-has-content": "error",
          "jsx-a11y/html-has-lang": "error",
          "jsx-a11y/iframe-has-title": "error",
          "jsx-a11y/img-redundant-alt": "error",
          "jsx-a11y/interactive-supports-focus": [
            "error",
            {
              tabbable: [
                "button",
                "checkbox",
                "link",
                "progressbar",
                "searchbox",
                "slider",
                "spinbutton",
                "switch",
                "textbox",
              ],
            },
          ],
          "jsx-a11y/label-has-associated-control": "error",
          "jsx-a11y/media-has-caption": "error",
          "jsx-a11y/mouse-events-have-key-events": "error",
          "jsx-a11y/no-access-key": "error",
          "jsx-a11y/no-autofocus": "error",
          "jsx-a11y/no-distracting-elements": "error",
          "jsx-a11y/no-interactive-element-to-noninteractive-role": "error",
          "jsx-a11y/no-noninteractive-element-interactions": [
            "error",
            {
              body: ["onError", "onLoad"],
              iframe: ["onError", "onLoad"],
              img: ["onError", "onLoad"],
            },
          ],
          "jsx-a11y/no-noninteractive-element-to-interactive-role": "error",
          "jsx-a11y/no-noninteractive-tabindex": "error",
          "jsx-a11y/no-redundant-roles": "error",
          "jsx-a11y/no-static-element-interactions": "error",
          "jsx-a11y/role-has-required-aria-props": "error",
          "jsx-a11y/role-supports-aria-props": "error",
          "jsx-a11y/scope": "error",
          "jsx-a11y/tabindex-no-positive": "error",
        },
        plugins: ["react", "jsx-a11y"],
        env: {
          browser: true,
        },
      },
    ],
    jsPlugins: [
      {
        name: "vite-plus",
        specifier: "vite-plus/oxlint-plugin",
      },
      {
        name: "crawlerai",
        specifier: "./lint/cognitive-complexity.js",
      },
    ],
    rules: {
      "vite-plus/prefer-vite-plus-imports": "error",
      // C11: cognitive complexity of at most 15 per function, the SonarCloud threshold (S3776).
      "crawlerai/cognitive-complexity": ["error", { max: 15 }],
      // SonarCloud S3358 (nested ternary), S7718 (catch
      // parameter `error`) and S1186 (an empty function says why in a comment, which ESLint's rule allows).
      "no-nested-ternary": "error",
      "unicorn/catch-error-name": "error",
      "no-empty-function": "error",
    },
  },
  fmt: {
    printWidth: 100,
    sortPackageJson: false,
    ignorePatterns: ["pnpm-lock.yaml", "openapi.json", "src/api/schema.d.ts", "src/api/limits.ts"],
  },
  plugins: [react(), tailwindcss()],
  // `pnpm dev` (frontend development) serves the screens and forwards API calls to the API on :8000, so the app
  // calls its own origin:
  // `/v1`, and `/healthz` at the root, so every path of the API is reachable. Anyone who reaches the dev server acts
  // with the key, so it listens on loopback only. The app calls its own
  // origin only, so no other origin may read a response the key was attached to: CORS is off.
  server: {
    host: "127.0.0.1",
    cors: false,
    proxy: { "/v1": backend, "/healthz": backend },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Timestamps render in the viewer's time zone; tests pin one so the expected text is the same everywhere.
    env: { TZ: "UTC" },
    css: false,
    // A screen test renders the whole app through its router: about 1 s alone, but several times that while the
    // suite's files run in parallel on a loaded machine (UAT F25, F35). One budget for every file, in place of a
    // per-file override that a new screen's tests forget.
    testTimeout: 20_000,
  },
});
