import { Button } from "@heroui/react";
import { useMapUrls } from "../../../api/hooks/jobs";
import { problemOf } from "../../../api/hooks/query";
import { OptionsToggle } from "../OptionsPanel";
import { OutputArea, type OutputState } from "../OutputArea";
import { NO_ERRORS, optionsChanged } from "../pageRequest";
import { PlaygroundLayout } from "../PlaygroundLayout";
import { requestUrl, UrlInput } from "../UrlInput";
import { usePageForm } from "../usePageForm";
import { buildMap, DEFAULT_MAP_OPTIONS, INITIAL_MAP } from "./form";
import { MapOptions } from "./MapOptions";
import { MapOutput } from "./MapOutput";

/** A map's request always can be sent: the server validates its URL and globs. */
const sendable = () => NO_ERRORS;

/** The Map playground at `/map` (SPEC-14 §4.2): a URL and its scope (`POST /v1/map`, answered at once), then the URLs
 * found as a table of links. Map takes no format or schema, so the toolbar has Options only. */
export function MapPlayground() {
  const map = useMapUrls();
  const problem = problemOf(map.error);
  const { form, setForm, optionsOpen, setOptionsOpen, validationErrors } = usePageForm(
    INITIAL_MAP,
    problem,
    sendable,
  );

  let state: OutputState | null = null;
  if (map.isPending) state = { kind: "pending", label: "Mapping the site" };
  else if (problem !== null) state = { kind: "failed", problem };
  else if (map.isSuccess) state = { kind: "done", content: <MapOutput result={map.data} /> };

  return (
    <PlaygroundLayout
      mode="map"
      validationErrors={validationErrors}
      onSubmit={() => {
        map.mutate(buildMap({ ...form, url: requestUrl(form.url) }));
      }}
      input={
        <UrlInput
          value={form.url}
          onChange={(url) => {
            setForm({ ...form, url });
          }}
        />
      }
      tools={
        <OptionsToggle
          isOpen={optionsOpen}
          changed={optionsChanged(form.options, DEFAULT_MAP_OPTIONS)}
          onChange={setOptionsOpen}
        />
      }
      action={
        <Button type="submit" isPending={map.isPending}>
          Map
        </Button>
      }
      options={
        optionsOpen ? (
          <MapOptions
            options={form.options}
            onChange={(options) => {
              setForm({ ...form, options });
            }}
          />
        ) : null
      }
    >
      {state === null ? null : <OutputArea state={state} />}
    </PlaygroundLayout>
  );
}
