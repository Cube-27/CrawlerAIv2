import { Checkbox, CheckboxGroup, Label } from "@heroui/react";
import type { ScrapeFormat } from "../api/scrape";

/** The formats in the order SPEC-07 §4.4 lists them; a request sends the chosen ones in this order. */
export const FORMATS: readonly (readonly [ScrapeFormat, string])[] = [
  ["markdown", "Markdown"],
  ["html", "HTML"],
  ["raw_html", "Raw HTML"],
  ["links", "Links"],
  ["metadata", "Metadata"],
  ["records", "Records"],
];

/** `chosen` in the order of `FORMATS`. */
export function orderedFormats(chosen: readonly string[]): ScrapeFormat[] {
  return FORMATS.map(([format]) => format).filter((format) => chosen.includes(format));
}

/** The page formats a scrape, batch or crawl request asks for (SPEC-07 §4.4), as a checkbox group. */
export function FormatChoices({
  value,
  onChange,
}: Readonly<{ value: readonly ScrapeFormat[]; onChange: (formats: ScrapeFormat[]) => void }>) {
  return (
    <CheckboxGroup
      value={[...value]}
      onChange={(values) => {
        onChange(orderedFormats(values));
      }}
    >
      <Label>Formats</Label>
      {FORMATS.map(([format, text]) => (
        <Checkbox key={format} value={format}>
          <Checkbox.Content>
            <Checkbox.Control>
              <Checkbox.Indicator />
            </Checkbox.Control>
            <Label>{text}</Label>
          </Checkbox.Content>
        </Checkbox>
      ))}
    </CheckboxGroup>
  );
}
