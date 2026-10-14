import { Alert, Checkbox, Fieldset, Label, TextArea, TextField, Typography } from "@heroui/react";
import { useState } from "react";
import { useMapUrls } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import type { MapResult } from "../../api/jobs";
import { LimitField } from "../../components/LimitField";
import { buildMap, INITIAL_MAP, type MapFormState } from "./form";
import { JobDialog } from "./JobDialog";
import { LinesField, UrlField } from "./JobFields";
import { JobForm } from "./JobForm";

function SourceCheckbox({
  label,
  value,
  onChange,
}: Readonly<{ label: string; value: boolean; onChange: (value: boolean) => void }>) {
  return (
    <Checkbox isSelected={value} onChange={onChange}>
      <Checkbox.Content>
        <Checkbox.Control>
          <Checkbox.Indicator />
        </Checkbox.Control>
        <Label>{label}</Label>
      </Checkbox.Content>
    </Checkbox>
  );
}

/** The URLs found, one per line, to read or copy into a batch. */
function MapResultView({ result }: Readonly<{ result: MapResult }>) {
  const { urls, sources, truncated } = result;
  return (
    <div className="flex flex-col gap-3">
      <Typography.Paragraph>
        {urls.length} URLs: {sources.sitemap} from sitemaps, {sources.links} from links.
      </Typography.Paragraph>
      {truncated ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>The list is cut short.</Alert.Title>
            <Alert.Description>
              More URLs were found than the limit, or reading stopped at a cap or the timeout.
            </Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      <TextField isReadOnly value={urls.join("\n")}>
        <Label>URLs found</Label>
        <TextArea rows={10} spellCheck={false} />
      </TextField>
    </div>
  );
}

function MapForm({ onCancel }: Readonly<{ onCancel: () => void }>) {
  const [form, setForm] = useState<MapFormState>(INITIAL_MAP);
  const map = useMapUrls();
  return (
    <div className="flex flex-col gap-6">
      <JobForm
        submitLabel="Map"
        problem={problemOf(map.error)}
        isPending={map.isPending}
        onCancel={onCancel}
        onSubmit={() => {
          map.mutate(buildMap(form));
        }}
      >
        <UrlField
          name="url"
          value={form.url}
          onChange={(url) => {
            setForm({ ...form, url });
          }}
        />
        <Fieldset>
          <Fieldset.Legend>Scope</Fieldset.Legend>
          <LinesField
            label="Include"
            name="include"
            description="URL globs, one per line. Empty: the URL's host."
            value={form.include}
            onChange={(include) => {
              setForm({ ...form, include });
            }}
          />
          <LinesField
            label="Exclude"
            name="exclude"
            description="URL globs, one per line, left out."
            value={form.exclude}
            onChange={(exclude) => {
              setForm({ ...form, exclude });
            }}
          />
          <LimitField
            label="URL limit"
            name="limit"
            value={form.limit}
            minValue={1}
            onChange={(limit) => {
              setForm({ ...form, limit });
            }}
          />
          <SourceCheckbox
            label="Read sitemaps"
            value={form.useSitemaps}
            onChange={(useSitemaps) => {
              setForm({ ...form, useSitemaps });
            }}
          />
          <SourceCheckbox
            label="Read the page's links"
            value={form.useLinks}
            onChange={(useLinks) => {
              setForm({ ...form, useLinks });
            }}
          />
        </Fieldset>
      </JobForm>
      {map.isSuccess ? <MapResultView result={map.data} /> : null}
    </div>
  );
}

/** `POST /v1/map` (SPEC-10 §4.4): a site's URLs, answered at once; it makes no job. */
export function MapDialog() {
  return (
    <JobDialog label="Map URLs" title="Map a site's URLs">
      {(close) => <MapForm onCancel={close} />}
    </JobDialog>
  );
}
