import { NumberRow, OptionsPanel, SwitchRow } from "../OptionsPanel";
import { ScopeRows } from "../rows";
import { DEFAULT_MAP_OPTIONS, type MapOptions as Options } from "./form";

/** Map's options: the scope globs, then the two sources and the URL limit. */
export function MapOptions({
  options,
  onChange,
}: Readonly<{ options: Options; onChange: (options: Options) => void }>) {
  return (
    <OptionsPanel
      onReset={() => {
        onChange(DEFAULT_MAP_OPTIONS);
      }}
    >
      <ScopeRows
        include={options.include}
        exclude={options.exclude}
        onChange={(scope) => {
          onChange({ ...options, ...scope });
        }}
      />
      <SwitchRow
        label="Use sitemaps"
        help="Reads the site's sitemaps for URLs: those robots.txt lists, else /sitemap.xml."
        isSelected={options.useSitemaps}
        onChange={(useSitemaps) => {
          onChange({ ...options, useSitemaps });
        }}
      />
      <SwitchRow
        label="Use links"
        help="Reads the links on the page at the URL."
        isSelected={options.useLinks}
        onChange={(useLinks) => {
          onChange({ ...options, useLinks });
        }}
      />
      <NumberRow
        label="Page limit"
        help="The most URLs the map returns. Empty: the server default."
        name="limit"
        value={options.limit}
        minValue={1}
        onChange={(limit) => {
          onChange({ ...options, limit });
        }}
      />
    </OptionsPanel>
  );
}
