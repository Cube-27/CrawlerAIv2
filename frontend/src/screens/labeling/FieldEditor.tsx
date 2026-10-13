import { Button, Checkbox, Input, Label, TextArea, TextField } from "@heroui/react";
import type { FieldDraft, FieldShape } from "./draft";

export interface FieldEditorProps {
  name: string;
  group: string; // the field's accessible name, e.g. "row 2 title"
  shape: FieldShape;
  field: FieldDraft;
  picking: boolean; // clicks on the page fill this field
  errors: string[]; // the API's or the form's reasons, for this field's path
  normalized: string | null; // what `/normalize` said about the raw text
  onChange: (field: FieldDraft) => void;
  onFocus: () => void;
  onNormalize: () => void;
}

/** One schema field's label (SPEC-03 §4.10): raw text, normalized value, `absent`, locator and distractors. */
export function FieldEditor({
  name,
  group,
  shape,
  field,
  picking,
  errors,
  normalized,
  onChange,
  onFocus,
  onNormalize,
}: FieldEditorProps) {
  const label = `${name} (${shape.type})`;

  return (
    <fieldset aria-label={group} className="flex flex-col gap-2 rounded border border-border p-3">
      <legend className="px-1 font-medium">
        {label}
        {picking ? " — picking from the page" : ""}
      </legend>
      <div className="flex items-end gap-2">
        <TextField
          onFocus={onFocus}
          className="flex-1"
          value={field.rawText}
          onChange={(rawText) => {
            onChange({ ...field, rawText });
          }}
        >
          <Label>Raw text</Label>
          <Input />
        </TextField>
        <Button
          variant="secondary"
          isDisabled={field.rawText.trim() === ""}
          onPress={onNormalize}
          aria-label={`Normalize ${group}`}
        >
          Normalize
        </Button>
      </div>
      {normalized === null ? null : <p className="text-sm text-muted">{normalized}</p>}
      <TextField
        onFocus={onFocus}
        value={field.value}
        isDisabled={field.absent}
        onChange={(value) => {
          onChange({ ...field, value });
        }}
      >
        <Label>Value (JSON)</Label>
        <Input />
      </TextField>
      <Checkbox
        onFocus={onFocus}
        isSelected={field.absent}
        onChange={(absent) => {
          onChange({ ...field, absent });
        }}
      >
        <Checkbox.Content>
          <Checkbox.Control>
            <Checkbox.Indicator />
          </Checkbox.Control>
          <Label>Absent from the page</Label>
        </Checkbox.Content>
      </Checkbox>
      <TextField
        onFocus={onFocus}
        value={field.locator}
        isDisabled={field.absent}
        onChange={(locator) => {
          onChange({ ...field, locator });
        }}
      >
        <Label>Locator</Label>
        <Input />
      </TextField>
      <TextField
        onFocus={onFocus}
        value={field.distractors}
        onChange={(distractors) => {
          onChange({ ...field, distractors });
        }}
      >
        <Label>Distractors (one JSON value per line)</Label>
        <TextArea rows={2} />
      </TextField>
      {errors.map((reason) => (
        <p key={reason} className="text-sm text-danger">
          Error: {reason}
        </p>
      ))}
    </fieldset>
  );
}
