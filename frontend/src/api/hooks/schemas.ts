import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import type { ApiClient } from "../client";
import {
  createSchema,
  draftSchema,
  getSchema,
  listSchemas,
  retireSchema,
  updateSchema,
  type NewSchema,
  type SchemaContent,
  type SchemaPageKind,
} from "../schemas";
import { unwrap } from "./query";

/** `/v1/schemas` as TanStack Query hooks. Every key starts with `schemas`, so one change invalidates them all. */
const SCHEMAS = ["schemas"] as const;

function listQuery(client: ApiClient, name?: string) {
  return {
    queryKey: [...SCHEMAS, "list", name ?? null],
    queryFn: () => unwrap(listSchemas(client, name)),
  };
}

/** Every version of every schema. */
export function useSchemas() {
  return useQuery(listQuery(useApiClient()));
}

/** Every version of the schema named `name`; waits while the name is not known yet. */
export function useSchemaVersions(name: string | undefined) {
  return useQuery({ ...listQuery(useApiClient(), name), enabled: name !== undefined });
}

/** One schema version; with a null `id`, nothing is read. */
export function useSchema(id: string | null) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...SCHEMAS, "one", id],
    queryFn: () => unwrap(getSchema(client, id ?? "")),
    enabled: id !== null,
  });
}

/** Mutations read the schemas again once they succeed: the server's answer, not a local patch. */
function useInvalidateSchemas() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: SCHEMAS });
}

export function useCreateSchema() {
  const client = useApiClient();
  const invalidate = useInvalidateSchemas();
  return useMutation({
    mutationFn: (body: NewSchema) => unwrap(createSchema(client, body)),
    onSuccess: invalidate,
  });
}

export function useUpdateSchema(id: string) {
  const client = useApiClient();
  const invalidate = useInvalidateSchemas();
  return useMutation({
    mutationFn: (body: SchemaContent) => unwrap(updateSchema(client, id, body)),
    onSuccess: invalidate,
  });
}

export function useRetireSchema() {
  const client = useApiClient();
  const invalidate = useInvalidateSchemas();
  return useMutation({
    mutationFn: (id: string) => unwrap(retireSchema(client, id)),
    onSuccess: invalidate,
  });
}

/** The draft of `fields` for `pageKind` pages (SPEC-14 §4.10). Drafting the same names again returns the same stored
 * draft, so it is read as a query: once per names and page kind, without retries (a failed draft is a problem to
 * show, and each attempt may be an LLM call). */
export function useFieldsDraft(fields: readonly string[], pageKind: SchemaPageKind) {
  const client = useApiClient();
  return useQuery({
    queryKey: [...SCHEMAS, "draft", pageKind, ...fields],
    queryFn: () => unwrap(draftSchema(client, { fields: [...fields], page_kind: pageKind })),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
}
