import { SchemaSelect } from "../../components/SchemaSelect";
import { FormatSelect } from "./FormatSelect";
import { OptionsToggle } from "./OptionsPanel";
import { optionsChanged, withSchema, type FormatForm } from "./pageRequest";

/** The toolbar of a mode that takes formats and a schema (Scrape, Batch, Crawl; SPEC-14 §4.2): Options, which marks a
 * setting that differs from `defaults`, then Format and Schema. `formatsUnused` disables Format when the request
 * sends no page format (a crawl with a schema asks for records alone). */
export function PageTools<F extends FormatForm>({
  form,
  defaults,
  optionsOpen,
  onOptionsOpen,
  formatsUnused = false,
  onChange,
}: Readonly<{
  form: F;
  defaults: F["options"];
  formatsUnused?: boolean;
  optionsOpen: boolean;
  onOptionsOpen: (isOpen: boolean) => void;
  onChange: (form: F) => void;
}>) {
  return (
    <>
      <OptionsToggle
        isOpen={optionsOpen}
        changed={optionsChanged(form.options, defaults)}
        onChange={onOptionsOpen}
      />
      <FormatSelect
        value={form.formats}
        isDisabled={formatsUnused}
        onChange={(formats) => {
          onChange({ ...form, formats });
        }}
      />
      <SchemaSelect
        value={form.schemaId}
        noneLabel="No schema"
        hideLabel
        onChange={(schemaId, schema) => {
          onChange(withSchema(form, schemaId, schema?.page_kind ?? null));
        }}
      />
    </>
  );
}
