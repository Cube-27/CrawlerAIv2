import { SchemaSelect } from "../../components/SchemaSelect";
import { FormatSelect } from "./FormatSelect";
import { OptionsToggle } from "./OptionsPanel";
import { optionsChanged, withSchema, type FormatForm } from "./pageRequest";

/** The toolbar of a mode that takes formats and a schema (Scrape, Batch, Crawl; SPEC-14 §4.2): Options, which marks a
 * setting that differs from `defaults`, then Format and Schema. */
export function PageTools<F extends FormatForm>({
  form,
  defaults,
  optionsOpen,
  onOptionsOpen,
  onChange,
}: Readonly<{
  form: F;
  defaults: F["options"];
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
