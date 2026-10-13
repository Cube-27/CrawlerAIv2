import {
  Button,
  Checkbox,
  Fieldset,
  Input,
  Label,
  TextArea,
  TextField,
  Typography,
} from "@heroui/react";
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
}: Readonly<FieldEditorProps>) {
  const label = `${name} (${shape.type})`;

  return (
    <Fieldset aria-label={group}>
      <Fieldset.Legend>
        {label}
        {picking ? " — picking from the page" : ""}
      </Fieldset.Legend>
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
      {normalized === null ? null : (
        <Typography.Paragraph size="sm" color="muted">
          {normalized}
        </Typography.Paragraph>
      )}
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
        <Typography.Paragraph key={reason} size="sm" className="text-danger">
          Error: {reason}
        </Typography.Paragraph>
      ))}
    </Fieldset>
  );
}
