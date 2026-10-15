import {
  Badge,
  Button,
  Disclosure,
  FieldError,
  Label,
  ListBox,
  NumberField,
  Select,
  Switch,
  ToggleButton,
  Tooltip,
} from "@heroui/react";
import { ArrowRotateLeft, CircleQuestion, Sliders } from "@gravity-ui/icons";
import { useId, type Key, type ReactNode } from "react";

/** The playground's options panel (SPEC-14 §4.2, DESIGN.md Options panel): rows of label, help icon and control, in
 * two columns from `md`, then a collapsed Advanced section and Reset settings. It is inline, never an overlay. */

/** The command bar's Options button. A dot shows when a setting differs from its default, and the button's description
 * says so. */
export function OptionsToggle({
  isOpen,
  changed,
  onChange,
}: Readonly<{ isOpen: boolean; changed: boolean; onChange: (isOpen: boolean) => void }>) {
  const changedId = useId();
  return (
    <Badge.Anchor>
      <ToggleButton
        isIconOnly
        variant="ghost"
        aria-label="Options"
        aria-controls="playground-options"
        aria-expanded={isOpen}
        {...(changed ? { "aria-describedby": changedId } : {})}
        isSelected={isOpen}
        onChange={onChange}
      >
        <Sliders aria-hidden="true" />
      </ToggleButton>
      {changed ? (
        <>
          <Badge aria-hidden="true" color="accent" size="sm" />
          <span id={changedId} hidden>
            Settings changed
          </span>
        </>
      ) : null}
    </Badge.Anchor>
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

/** A row's left side: the control's label and its help icon. */
function RowLabel({ label, help }: Readonly<{ label: string; help: string }>) {
  return (
    <span className="flex items-center gap-1.5">
      <Label>{label}</Label>
      <Help label={label} text={help} />
    </span>
  );
}

const ROW = "flex flex-row items-center justify-between gap-3";

export function SwitchRow({
  label,
  help,
  isSelected,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  isSelected: boolean;
  onChange: (isSelected: boolean) => void;
}>) {
  // The label and the track are one clickable element (Switch.Content), so the help icon follows the track.
  return (
    <Switch className={ROW} isSelected={isSelected} onChange={onChange}>
      <Switch.Content className="flex-1 justify-between">
        <Label>{label}</Label>
        <Switch.Control>
          <Switch.Thumb />
        </Switch.Control>
      </Switch.Content>
      <Help label={label} text={help} />
    </Switch>
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
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  options: readonly (readonly [K, string])[];
  value: K | null;
  placeholder?: string;
  disabled?: readonly K[];
  onChange: (value: K) => void;
}>) {
  return (
    <Select
      className={ROW}
      name={name}
      value={value}
      {...(placeholder === undefined ? {} : { placeholder })}
      disabledKeys={disabled}
      onChange={(key: Key | null) => {
        const chosen = options.find(([option]) => option === key);
        if (chosen !== undefined) onChange(chosen[0]);
      }}
    >
      <RowLabel label={label} help={help} />
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

/** A whole number of at least `minValue`; empty (NaN) leaves it to the server. `name` is the request member a server
 * error names. */
export function NumberRow({
  label,
  help,
  name,
  value,
  minValue,
  maxValue,
  onChange,
}: Readonly<{
  label: string;
  help: string;
  name: string;
  value: number;
  minValue: number;
  maxValue?: number;
  onChange: (value: number) => void;
}>) {
  return (
    <NumberField
      className={ROW}
      name={name}
      value={value}
      minValue={minValue}
      {...(maxValue === undefined ? {} : { maxValue })}
      formatOptions={{ maximumFractionDigits: 0, useGrouping: false }}
      onChange={onChange}
    >
      <RowLabel label={label} help={help} />
      <NumberField.Group>
        <NumberField.DecrementButton />
        <NumberField.Input placeholder="Default" />
        <NumberField.IncrementButton />
      </NumberField.Group>
    </NumberField>
  );
}

const GRID = "grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-2";

export function OptionsPanel({
  advanced,
  onReset,
  children,
}: Readonly<{ advanced: ReactNode; onReset: () => void; children: ReactNode }>) {
  return (
    <section
      id="playground-options"
      aria-label="Options"
      className="flex flex-col gap-4 rounded-xl border border-border p-4"
    >
      <div className={GRID}>{children}</div>
      <Disclosure>
        <Disclosure.Heading>
          <Button slot="trigger" variant="ghost" size="sm">
            Advanced
            <Disclosure.Indicator />
          </Button>
        </Disclosure.Heading>
        <Disclosure.Content>
          <Disclosure.Body className={`${GRID} pt-3`}>{advanced}</Disclosure.Body>
        </Disclosure.Content>
      </Disclosure>
      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onPress={onReset}>
          <ArrowRotateLeft aria-hidden="true" />
          Reset settings
        </Button>
      </div>
    </section>
  );
}
