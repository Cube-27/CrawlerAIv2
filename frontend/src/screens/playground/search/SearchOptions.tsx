import { NumberRow, OptionsPanel, SwitchRow } from "../OptionsPanel";
import { MetadataRow } from "../rows";
import { DEFAULT_SEARCH_OPTIONS, type SearchOptions as Options } from "./form";

/** Search's options (D-1442): the result limit, and whether the results are scraped; the toolbar's Format and Schema
 * say how, and Metadata in JSON adds each page's metadata to the output. */
export function SearchOptions({
  options,
  onChange,
}: Readonly<{ options: Options; onChange: (options: Options) => void }>) {
  return (
    <OptionsPanel
      onReset={() => {
        onChange(DEFAULT_SEARCH_OPTIONS);
      }}
    >
      <NumberRow
        label="Result limit"
        help="The most results. Empty: the server default."
        name="limit"
        value={options.limit}
        minValue={1}
        maxValue={50}
        onChange={(limit) => {
          onChange({ ...options, limit });
        }}
      />
      <SwitchRow
        label="Scrape results"
        help="Queues a batch job that scrapes every result with the toolbar's Format and Schema."
        isSelected={options.scrape}
        onChange={(scrape) => {
          onChange({ ...options, scrape });
        }}
      />
      <MetadataRow
        isSelected={options.metadataInJson}
        onChange={(metadataInJson) => {
          onChange({ ...options, metadataInJson });
        }}
      />
    </OptionsPanel>
  );
}
