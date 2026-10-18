import {
  Badge,
  Button,
  Checkbox,
  CheckboxGroup,
  FieldError,
  Input,
  Label,
  ListBox,
  NumberField,
  Popover,
  Select,
  Switch,
  Tag,
  TagGroup,
  TextArea,
  TextField,
  Tooltip,
} from "@heroui/react";
import { ArrowRotateLeft, CircleQuestion, Sliders } from "@gravity-ui/icons";
import { use, useId, useRef, useState, type Key, type ReactNode } from "react";
import { ReadOnlyContext } from "./readOnly";

/** The playground's options (SPEC-14 §4.2, DESIGN.md Playground options): a popover from the command bar's Options
 * button with every setting at once, in a grid of cells (label and help icon over the control): four columns from
 * `sm`, one at phone width; a list or free text takes two columns or the whole width. It is an overlay, so opening it
 * moves nothing on the page. */

/** The command bar's Options button and the popover it opens, holding `children` (a mode's `OptionsPanel`). A dot
 * shows when a setting differs from its default, and the button's description says so. */
export function OptionsPopover({
  isOpen,
  changed,
  onOpenChange,
  children,
}: Readonly<{
  isOpen: boolean;
  changed: boolean;
  onOpenChange: (isOpen: boolean) => void;
  children: ReactNode;
}>) {
  const changedId = useId();
  const dialog = useRef<HTMLElement>(null);
  // A number field commits its text on blur (React Aria NumberField), and Escape removes the popover while the field
  // has focus, so the number typed last would be lost: the focused control is blurred first.
  const change = (open: boolean) => {
    const focused = document.activeElement;
    if (!open && focused instanceof HTMLElement && dialog.current?.contains(focused) === true)
      focused.blur();
    onOpenChange(open);
  };
  return (
    <Popover isOpen={isOpen} onOpenChange={change}>
      <Badge.Anchor>
        <Button
          isIconOnly
          variant="ghost"
          aria-label="Options"
          {...(changed ? { "aria-describedby": changedId } : {})}
        >
          <Sliders aria-hidden="true" />
        </Button>
        {changed ? (
          <>
            <Badge aria-hidden="true" color="accent" size="sm" />
            <span id={changedId} hidden>
              Settings changed
            </span>
          </>
        ) : null}
      </Badge.Anchor>
      {/* Outlined like the command bar; it scrolls inside the height React Aria leaves it in the viewport. */}
      <Popover.Content
        placement="bottom start"
        className="w-options overflow-auto border border-border"
      >
        <Popover.Dialog ref={dialog} className="options-panel">
          {children}
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  );
}

function Help({ label, text }: Readonly<{ label: string; text: string }>) {
  return (
    <Tooltip delay={0}>
      <Tooltip.Trigger aria-label={`About ${label}`} className="inline-flex text-muted">
        <CircleQuestion aria-hidden="true" />
      </Tooltip.Trigger>
      <Tooltip.Content>{text}</Tooltip.Content>
    </Tooltip>
  );
}

/** A cell's top line: the control's label and its help icon. `id` names the control when the label is not the
 * field's own (a switch). */
function CellLabel({ label, help, id }: Readonly<{ label: string; help: string; id?: string }>) {
  return (
    <span className="flex items-center gap-1.5">
      <Label {...(id === undefined ? {} : { id })}>{label}</Label>
      <Help label={label} text={help} />
    </span>
  );
}

/** One grid cell; a wide one (a list of entries, a URL) spans two columns from `sm`. */
const CELL = "flex min-w-0 flex-col gap-1.5";
const WIDE_CELL = `${CELL} sm:col-span-2`;
/** A cell across the whole grid: free text over several lines, rows of rules. */
const FULL_CELL = `${CELL} col-span-full`;

export function SwitchRow({
  label,
  help,
  isSelected,
  isDisabled = false,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  isSelected: boolean;
  isDisabled?: boolean;
  onChange: (isSelected: boolean) => void;
}>) {
  // The label sits above the track like every cell's, so the help icon can follow it outside the clickable track.
  const labelId = useId();
  return (
    <div className={CELL}>
      <CellLabel label={label} help={help} id={labelId} />
      <Switch
        aria-labelledby={labelId}
        className="h-9 justify-center"
        isSelected={isSelected}
        isDisabled={isDisabled}
        onChange={onChange}
      >
        <Switch.Content>
          <Switch.Control>
            <Switch.Thumb />
          </Switch.Control>
        </Switch.Content>
      </Switch>
    </div>
  );
}

/** One choice among `options`; null shows `placeholder`. `name` is the request member a server error names. */
export function SelectRow<K extends string>({
  label,
  help,
  name,
  options,
  value,
  placeholder,
  disabled = [],
  isDisabled = false,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  options: readonly (readonly [K, string])[];
  value: K | null;
  placeholder?: string;
  disabled?: readonly K[];
  /** The whole row: kept in place, unusable (a setting that does not apply now). */
  isDisabled?: boolean;
  onChange: (value: K) => void;
}>) {
  return (
    <Select
      className={CELL}
      name={name}
      value={value}
      {...(placeholder === undefined ? {} : { placeholder })}
      disabledKeys={disabled}
      isDisabled={isDisabled}
      onChange={(key: Key | null) => {
        const chosen = options.find(([option]) => option === key);
        if (chosen !== undefined) onChange(chosen[0]);
      }}
    >
      <CellLabel label={label} help={help} />
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {options.map(([option, text]) => (
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

/** A whole number of at least `minValue`; empty (NaN) leaves it out, and `placeholder` says what that means. `name`
 * is the request member a server error names. */
export function NumberRow({
  label,
  help,
  name,
  value,
  minValue,
  maxValue,
  placeholder = "Default",
  fractionDigits = 0,
  isDisabled = false,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  value: number;
  minValue: number;
  maxValue?: number;
  fractionDigits?: number;
  placeholder?: string;
  isDisabled?: boolean;
  onChange: (value: number) => void;
}>) {
  return (
    <NumberField
      className={CELL}
      name={name}
      value={value}
      minValue={minValue}
      {...(maxValue === undefined ? {} : { maxValue })}
      formatOptions={{ maximumFractionDigits: fractionDigits, useGrouping: false }}
      isDisabled={isDisabled}
      onChange={onChange}
    >
      <CellLabel label={label} help={help} />
      <NumberField.Group>
        <NumberField.DecrementButton />
        <NumberField.Input placeholder={placeholder} />
        <NumberField.IncrementButton />
      </NumberField.Group>
    </NumberField>
  );
}

/** Free text; empty leaves the member out. `name` is the request member a server error names. */
export function TextRow({
  label,
  help,
  name,
  value,
  placeholder,
  isDisabled = false,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  value: string;
  placeholder: string;
  isDisabled?: boolean;
  onChange: (value: string) => void;
}>) {
  return (
    <TextField
      className={WIDE_CELL}
      name={name}
      value={value}
      isDisabled={isDisabled}
      onChange={onChange}
    >
      <CellLabel label={label} help={help} />
      <Input autoComplete="off" spellCheck={false} placeholder={placeholder} />
      <FieldError />
    </TextField>
  );
}

/** Free text over several lines, across the grid; empty leaves the member out. `name` is the request member a server
 * error names. */
export function TextAreaRow({
  label,
  help,
  name,
  value,
  placeholder,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  value: string;
  placeholder: string;
  onChange: (value: string) => void;
}>) {
  return (
    <TextField className={FULL_CELL} name={name} value={value} onChange={onChange}>
      <CellLabel label={label} help={help} />
      <TextArea rows={4} spellCheck={false} placeholder={placeholder} />
      <FieldError />
    </TextField>
  );
}

/** Any of `options`, as checkboxes across the grid. `name` is the request member a server error names. */
export function CheckboxesRow<K extends string>({
  label,
  help,
  name,
  options,
  values,
  isDisabled = false,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  options: readonly (readonly [K, string])[];
  values: readonly K[];
  isDisabled?: boolean;
  onChange: (values: K[]) => void;
}>) {
  return (
    <CheckboxGroup
      className={FULL_CELL}
      name={name}
      value={[...values]}
      isDisabled={isDisabled}
      onChange={(next: string[]) => {
        onChange(options.map(([option]) => option).filter((option) => next.includes(option)));
      }}
    >
      <CellLabel label={label} help={help} />
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {options.map(([option, text]) => (
          <Checkbox key={option} value={option}>
            <Checkbox.Content>
              <Checkbox.Control>
                <Checkbox.Indicator />
              </Checkbox.Control>
              <Label>{text}</Label>
            </Checkbox.Content>
          </Checkbox>
        ))}
      </div>
      <FieldError />
    </CheckboxGroup>
  );
}

/** A list of entries, each added from the text field with Add (or Enter) and removed from its tag; an entry already
 * listed is not added again, and one `refuse` gives a reason for stays in the field with that reason. `name` is the
 * request member a server error names. */
export function TagListRow({
  label,
  help,
  name,
  values,
  placeholder,
  refuse = () => null,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  values: readonly string[];
  placeholder: string;
  refuse?: (entry: string) => string | null;
  onChange: (values: string[]) => void;
}>) {
  const [draft, setDraft] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  // A tag's remove is a keyboard action too (Delete, Backspace), which a disabled fieldset does not block.
  const readOnly = use(ReadOnlyContext);
  const add = () => {
    const entry = draft.trim();
    if (entry === "") return;
    const reason = refuse(entry);
    setRefused(reason);
    if (reason !== null) return;
    onChange(values.includes(entry) ? [...values] : [...values, entry]);
    setDraft("");
  };
  const removal = readOnly
    ? {}
    : {
        onRemove: (keys: Set<Key>) => {
          onChange(values.filter((value) => !keys.has(value)));
        },
      };
  return (
    <div className={WIDE_CELL}>
      <TextField
        className="flex flex-col gap-1.5"
        name={name}
        value={draft}
        isInvalid={refused !== null}
        onChange={(text) => {
          setDraft(text);
          setRefused(null);
        }}
      >
        <CellLabel label={label} help={help} />
        <div className="flex items-center gap-2">
          <Input
            className="min-w-0 flex-1"
            autoComplete="off"
            spellCheck={false}
            placeholder={placeholder}
            onKeyDown={(event) => {
              // Enter adds the entry instead of sending the form.
              if (event.key !== "Enter") return;
              event.preventDefault();
              add();
            }}
          />
          <Button variant="secondary" aria-label={`Add to ${label}`} onPress={add}>
            Add
          </Button>
        </div>
        <FieldError>{refused ?? undefined}</FieldError>
      </TextField>
      {values.length === 0 ? null : (
        <TagGroup aria-label={label} size="sm" {...removal}>
          <TagGroup.List>
            {values.map((value) => (
              <Tag key={value} id={value} textValue={value}>
                {value}
              </Tag>
            ))}
          </TagGroup.List>
        </TagGroup>
      )}
    </div>
  );
}

/** A mode's settings in the options popover: its heading and Reset settings on one line, then every setting in the
 * grid. Read-only, the settings are disabled (a disabled fieldset, HTML §4.10.15) and can still be read. */
export function OptionsPanel({
  onReset,
  children,
}: Readonly<{ onReset: () => void; children: ReactNode }>) {
  const readOnly = use(ReadOnlyContext);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <Popover.Heading slot="title">Options</Popover.Heading>
        <Button variant="ghost" size="sm" isDisabled={readOnly} onPress={onReset}>
          <ArrowRotateLeft aria-hidden="true" />
          Reset settings
        </Button>
      </div>
      <fieldset
        disabled={readOnly}
        className="grid grid-cols-1 items-start gap-x-4 gap-y-4 sm:grid-cols-4"
      >
        {children}
      </fieldset>
    </div>
  );
}
