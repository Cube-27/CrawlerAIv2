import type { MethodHint, PageKind } from "../../api/scrape";
import { METHOD_HINTS, PAGE_KINDS } from "../../components/requestOptions";
import { SelectRow, SwitchRow, TextRow } from "./OptionsPanel";

/** Options rows more than one mode has (SPEC-14 §4.2), each named after its request member. */

/** `page_kind`. With a schema, the page kind is the one its records can be for, `schemaPageKind`, or none (SPEC-07
 * §4.4), and the others are disabled. */
export function PageKindRow({
  value,
  hasSchema,
  schemaPageKind,
  onChange,
}: Readonly<{
  value: PageKind | null;
  hasSchema: boolean;
  schemaPageKind: PageKind | null;
  onChange: (pageKind: PageKind) => void;
}>) {
  return (
    <SelectRow<PageKind>
      label="Page kind"
      help="Whether the page shows one item or a list of items. With a schema, it is the schema's; records of listing pages are not available yet."
      name="page_kind"
      options={PAGE_KINDS}
      value={hasSchema ? schemaPageKind : value}
      placeholder="Not set"
      disabled={
        hasSchema ? PAGE_KINDS.map(([kind]) => kind).filter((kind) => kind !== schemaPageKind) : []
      }
      onChange={onChange}
    />
  );
}

/** The Metadata in JSON view option: it asks for the `metadata` format, and for a job's `include=metadata`. */
export function MetadataRow({
  isSelected,
  onChange,
}: Readonly<{ isSelected: boolean; onChange: (isSelected: boolean) => void }>) {
  return (
    <SwitchRow
      label="Metadata in JSON"
      help="Adds the page's metadata (title, description, language, canonical URL) to the output."
      isSelected={isSelected}
      onChange={onChange}
    />
  );
}

/** `fetch.method_hint`. */
export function FetchMethodRow({
  value,
  onChange,
}: Readonly<{ value: MethodHint; onChange: (methodHint: MethodHint) => void }>) {
  return (
    <SelectRow<MethodHint>
      label="Fetch method"
      help="How the page is fetched. Auto starts with HTTP and moves to a browser when the page needs one."
      name="fetch.method_hint"
      options={METHOD_HINTS}
      value={value}
      onChange={onChange}
    />
  );
}

/** `webhook_url`: where the job's end is posted (SPEC-10 §4.2). */
export function WebhookRow({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (webhookUrl: string) => void }>) {
  return (
    <TextRow
      label="Webhook URL"
      help="Where the job's summary is posted when it ends. Empty: no webhook."
      name="webhook_url"
      value={value}
      placeholder="None"
      onChange={onChange}
    />
  );
}
