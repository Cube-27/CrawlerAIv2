import { Description, FieldError, Label, NumberField } from "@heroui/react";

/** A whole number of at least `minValue`; empty (NaN) leaves the value to the server. `name` is the request member a
 * server error names. */
export function LimitField({
  label,
  name,
  value,
  minValue,
  maxValue,
  onChange,
}: Readonly<{
  label: string;
  name: string;
  value: number;
  minValue: number;
  maxValue?: number;
  onChange: (value: number) => void;
}>) {
  return (
    <NumberField
      name={name}
      value={value}
      minValue={minValue}
      {...(maxValue === undefined ? {} : { maxValue })}
      formatOptions={{ maximumFractionDigits: 0, useGrouping: false }}
      onChange={onChange}
    >
      <Label>{label}</Label>
      <NumberField.Group>
        <NumberField.DecrementButton />
        <NumberField.Input />
        <NumberField.IncrementButton />
      </NumberField.Group>
      <Description>Empty: the server default.</Description>
      <FieldError />
    </NumberField>
  );
}
