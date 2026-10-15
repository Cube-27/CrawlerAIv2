import { FieldError, Label, ListBox, Select } from "@heroui/react";
import type { Key } from "react";

/** The guard `accepts` takes for `options`: a key of its own, not one it inherits (such as `toString`). */
export function isOptionOf<K extends string>(options: Readonly<Record<K, string>>) {
  return (key: unknown): key is K => typeof key === "string" && Object.hasOwn(options, key);
}

/** A labelled HeroUI Select over a `Record` of option labels. With `hideLabel`, the label is its accessible name only,
 * for a toolbar. */
export function OptionSelect<K extends string>({
  label,
  options,
  value,
  isRequired = false,
  hideLabel = false,
  accepts,
  onChange,
}: Readonly<{
  label: string;
  options: Readonly<Record<K, string>>;
  value: K | null;
  isRequired?: boolean;
  hideLabel?: boolean;
  accepts: (key: unknown) => key is K;
  onChange: (value: K) => void;
}>) {
  return (
    <Select
      isRequired={isRequired}
      value={value}
      {...(hideLabel ? { "aria-label": label } : {})}
      onChange={(key: Key | null) => {
        if (accepts(key)) onChange(key);
      }}
    >
      {hideLabel ? null : <Label>{label}</Label>}
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {Object.entries<string>(options).map(([option, text]) => (
            <ListBox.Item key={option} id={option} textValue={text}>
              {text}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
      <FieldError />
    </Select>
  );
}
