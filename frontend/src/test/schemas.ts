import type { components } from "../api/schema";

type FieldSpec = components["schemas"]["FieldSpec-Output"];

/** A field spec as the server sends it, every member present; `overrides` replaces any of them. */
export function fieldSpec(overrides: Partial<FieldSpec>): FieldSpec {
  return {
    type: "text",
    required: false,
    scope: "row",
    description: null,
    fields: null,
    item: null,
    key: null,
    scheme: null,
    schema_org: null,
    vocab: null,
    ...overrides,
  };
}
