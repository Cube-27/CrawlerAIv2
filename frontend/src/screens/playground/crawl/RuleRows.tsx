import { Button, Description, Input, Label, ListBox, Select, TextField } from "@heroui/react";
import { Plus, TrashBin } from "@gravity-ui/icons";
import type { Key } from "react";
import type { PageKind } from "../../../api/scrape";
import { PAGE_KINDS } from "../../../components/requestOptions";
import type { RuleRow } from "./form";

function PageKindPicker({
  label,
  value,
  fixed,
  onChange,
}: Readonly<{
  label: string;
  value: PageKind;
  fixed: PageKind | null;
  onChange: (pageKind: PageKind) => void;
}>) {
  return (
    <Select
      aria-label={label}
      className="w-36"
      value={fixed ?? value}
      disabledKeys={
        fixed === null ? [] : PAGE_KINDS.map(([kind]) => kind).filter((kind) => kind !== fixed)
      }
      onChange={(key: Key | null) => {
        const chosen = PAGE_KINDS.find(([kind]) => kind === key);
        if (chosen !== undefined) onChange(chosen[0]);
      }}
    >
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {PAGE_KINDS.map(([kind, text]) => (
            <ListBox.Item key={kind} id={kind} textValue={text}>
              {text}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

/** A crawl's `page_kind_rules` (SPEC-10 §4.5) as rows of a URL glob and a page kind, across the panel's width.
 * Without rules every page in scope is extracted; with rules, a page no glob matches is read for its links only. With
 * a schema every rule is for its page kind, `fixed`. `error` is why the rules can't be sent. */
export function RuleRows({
  rules,
  fixed,
  error,
  onChange,
}: Readonly<{
  rules: readonly RuleRow[];
  fixed: PageKind | null;
  error: string | undefined;
  onChange: (rules: RuleRow[]) => void;
}>) {
  const replace = (key: string, next: RuleRow) => {
    onChange(rules.map((rule) => (rule.key === key ? next : rule)));
  };
  return (
    <fieldset className="flex flex-col gap-2 md:col-span-2">
      <legend className="contents">
        <Label>Page-kind rules</Label>
      </legend>
      {rules.map((rule, index) => {
        const n = String(index + 1);
        return (
          <div key={rule.key} className="flex items-center gap-2">
            <TextField
              aria-label={`Pattern ${n}`}
              className="flex-1"
              value={rule.pattern}
              onChange={(pattern) => {
                replace(rule.key, { ...rule, pattern });
              }}
            >
              <Input
                autoComplete="off"
                spellCheck={false}
                placeholder="https://example.com/items/*"
              />
            </TextField>
            <PageKindPicker
              label={`Page kind ${n}`}
              value={rule.pageKind}
              fixed={fixed}
              onChange={(pageKind) => {
                replace(rule.key, { ...rule, pageKind });
              }}
            />
            <Button
              isIconOnly
              size="sm"
              variant="ghost"
              aria-label={`Remove rule ${n}`}
              onPress={() => {
                onChange(rules.filter(({ key }) => key !== rule.key));
              }}
            >
              <TrashBin aria-hidden="true" />
            </Button>
          </div>
        );
      })}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Description>
          A URL glob per rule; a page no rule matches is read for its links only.
        </Description>
        <Button
          size="sm"
          variant="secondary"
          onPress={() => {
            onChange([
              ...rules,
              { key: crypto.randomUUID(), pattern: "", pageKind: fixed ?? "detail" },
            ]);
          }}
        >
          <Plus aria-hidden="true" />
          Add rule
        </Button>
      </div>
      {/* Not one field's error, so React Aria's FieldError has no field to follow: the message is shown as an alert. */}
      {error === undefined ? null : (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
