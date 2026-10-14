import { Button, Description, Fieldset, Input, Label, TextField } from "@heroui/react";
import { Choices } from "../../components/Choices";
import { PAGE_KINDS } from "../../components/requestOptions";
import type { RuleRow } from "./form";

/** A crawl's page-kind rules (SPEC-10 §4.5) as rows of a pattern and a page kind. Without rules every page in scope is
 * extracted; with rules, a page no pattern matches is read for its links only. */
export function PageKindRules({
  rules,
  onChange,
}: Readonly<{ rules: readonly RuleRow[]; onChange: (rules: RuleRow[]) => void }>) {
  const replace = (key: string, next: RuleRow) => {
    onChange(rules.map((rule) => (rule.key === key ? next : rule)));
  };
  return (
    <Fieldset>
      <Fieldset.Legend>Page-kind rules</Fieldset.Legend>
      {rules.map((rule, index) => {
        const n = String(index + 1);
        return (
          <div key={rule.key} className="flex flex-wrap items-end gap-3">
            <TextField
              value={rule.pattern}
              onChange={(pattern) => {
                replace(rule.key, { ...rule, pattern });
              }}
            >
              <Label>Pattern {n}</Label>
              <Input autoComplete="off" spellCheck={false} />
            </TextField>
            <Choices
              label={`Page kind ${n}`}
              options={PAGE_KINDS}
              value={rule.pageKind}
              onChange={(pageKind) => {
                replace(rule.key, { ...rule, pageKind });
              }}
            />
            <Button
              variant="ghost"
              onPress={() => {
                onChange(rules.filter(({ key }) => key !== rule.key));
              }}
            >
              Remove rule {n}
            </Button>
          </div>
        );
      })}
      <Description>
        A URL glob per rule; a page no rule matches is read for its links only.
      </Description>
      <div>
        <Button
          variant="secondary"
          onPress={() => {
            onChange([...rules, { key: crypto.randomUUID(), pattern: "", pageKind: "detail" }]);
          }}
        >
          Add rule
        </Button>
      </div>
    </Fieldset>
  );
}
