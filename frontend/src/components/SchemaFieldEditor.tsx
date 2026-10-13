import {
  Button,
  Checkbox,
  FieldError,
  Fieldset,
  Input,
  Label,
  ListBox,
  Radio,
  RadioGroup,
  Select,
  TextArea,
  TextField,
} from "@heroui/react";
import { useState, type Key } from "react";
import type { FieldSpecInput } from "../api/schemas";
import {
  FIELD_TYPES,
  isFieldSpec,
  isFieldSpecs,
  isFieldType,
  isScheme,
  parseJson,
  SCHEMES,
  withType,
  type FieldRow,
} from "./schemaDocument";

/** An optional text member: an empty input sends null, which the API reads as not set. */
function optional(text: string): string | null {
  return text === "" ? null : text;
}

/** A labelled HeroUI Select over a `Record` of option labels. */
function OptionSelect<K extends string>({
  label,
  options,
  value,
  isRequired = false,
  accepts,
  onChange,
}: Readonly<{
  label: string;
  options: Readonly<Record<K, string>>;
  value: K | null;
  isRequired?: boolean;
  accepts: (key: unknown) => key is K;
  onChange: (value: K) => void;
}>) {
  return (
    <Select
      isRequired={isRequired}
      value={value}
      onChange={(key: Key | null) => {
        if (accepts(key)) onChange(key);
      }}
    >
      <Label>{label}</Label>
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

/** A nested member (`item`, `fields`) edited as JSON; the spec changes only while the text is that member's shape. */
function JsonMember<T>({
  label,
  value,
  accepts,
  onChange,
}: Readonly<{
  label: string;
  value: T | null | undefined;
  accepts: (value: unknown) => value is T;
  onChange: (value: T) => void;
}>) {
  const [text, setText] = useState(() => (value == null ? "" : JSON.stringify(value, null, 2)));
  return (
    <TextField
      isRequired
      value={text}
      validate={(next) =>
        accepts(parseJson(next)) ? null : "Enter a field spec with a known type as JSON."
      }
      onChange={(next) => {
        setText(next);
        const parsed = parseJson(next);
        if (accepts(parsed)) onChange(parsed);
      }}
    >
      <Label>{label}</Label>
      <TextArea rows={4} />
      <FieldError />
    </TextField>
  );
}

/** The inputs only `spec.type` takes (SPEC-04 §4.1): a vocabulary, a scheme, a list item or object fields. */
function TypeParameters({
  spec,
  onChange,
}: Readonly<{ spec: FieldSpecInput; onChange: (spec: FieldSpecInput) => void }>) {
  switch (spec.type) {
    case "enum":
      return (
        <TextField
          isRequired
          value={spec.vocab ?? ""}
          onChange={(vocab) => {
            onChange({ ...spec, vocab: optional(vocab) });
          }}
        >
          <Label>Vocabulary</Label>
          <Input autoComplete="off" />
          <FieldError />
        </TextField>
      );
    case "identifier":
      return (
        <OptionSelect
          label="Scheme"
          options={SCHEMES}
          value={spec.scheme ?? null}
          isRequired
          accepts={isScheme}
          onChange={(scheme) => {
            onChange({ ...spec, scheme });
          }}
        />
      );
    case "list":
      return (
        <JsonMember
          label="Item (JSON)"
          value={spec.item}
          accepts={isFieldSpec}
          onChange={(item) => {
            onChange({ ...spec, item });
          }}
        />
      );
    case "object":
      return (
        <JsonMember
          label="Fields (JSON)"
          value={spec.fields}
          accepts={isFieldSpecs}
          onChange={(fields) => {
            onChange({ ...spec, fields });
          }}
        />
      );
    default:
      return null;
  }
}

/** One field of a schema: its name, type, flags and description, then the parameters its type takes. */
export function SchemaFieldEditor({
  row,
  index,
  isDuplicate,
  onChange,
  onRemove,
}: Readonly<{
  row: FieldRow;
  index: number;
  isDuplicate: (name: string) => boolean;
  onChange: (row: FieldRow) => void;
  onRemove: () => void;
}>) {
  const { spec } = row;
  const setSpec = (next: FieldSpecInput) => {
    onChange({ ...row, spec: next });
  };
  const number = String(index + 1);
  return (
    <Fieldset>
      <Fieldset.Legend>Field {number}</Fieldset.Legend>
      <TextField
        isRequired
        name={`fields.${row.name.trim()}`}
        value={row.name}
        validate={(name) => (isDuplicate(name) ? "Another field has this name." : null)}
        onChange={(name) => {
          onChange({ ...row, name });
        }}
      >
        <Label>Field name</Label>
        <Input autoComplete="off" />
        <FieldError />
      </TextField>
      <OptionSelect
        label="Type"
        options={FIELD_TYPES}
        value={spec.type}
        isRequired
        accepts={isFieldType}
        onChange={(type) => {
          setSpec(withType(spec, type));
        }}
      />
      <TypeParameters key={spec.type} spec={spec} onChange={setSpec} />
      <Checkbox
        isSelected={spec.required}
        onChange={(required) => {
          setSpec({ ...spec, required });
        }}
      >
        <Checkbox.Content>
          <Checkbox.Control>
            <Checkbox.Indicator />
          </Checkbox.Control>
          <Label>Required</Label>
        </Checkbox.Content>
      </Checkbox>
      <RadioGroup
        value={spec.scope}
        orientation="horizontal"
        onChange={(scope) => {
          if (scope === "row" || scope === "page") setSpec({ ...spec, scope });
        }}
      >
        <Label>Scope</Label>
        {(["row", "page"] as const).map((scope) => (
          <Radio key={scope} value={scope}>
            <Radio.Content>
              <Radio.Control>
                <Radio.Indicator />
              </Radio.Control>
              <Label>{scope === "row" ? "Row" : "Page"}</Label>
            </Radio.Content>
          </Radio>
        ))}
      </RadioGroup>
      <TextField
        value={spec.description ?? ""}
        onChange={(description) => {
          setSpec({ ...spec, description: optional(description) });
        }}
      >
        <Label>Description</Label>
        <Input autoComplete="off" />
      </TextField>
      <TextField
        value={spec.schema_org ?? ""}
        onChange={(schemaOrg) => {
          setSpec({ ...spec, schema_org: optional(schemaOrg) });
        }}
      >
        <Label>schema.org property</Label>
        <Input autoComplete="off" />
      </TextField>
      <div className="flex justify-end">
        <Button variant="ghost" aria-label={`Remove field ${number}`} onPress={onRemove}>
          Remove
        </Button>
      </div>
    </Fieldset>
  );
}
