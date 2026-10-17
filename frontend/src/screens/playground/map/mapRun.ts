import { useState } from "react";
import { useLocation, useNavigate } from "react-router";
import type { MapResult } from "../../../api/jobs";
import { isJsonObject } from "../../../api/json";
import type { MapFormState } from "./form";

/** A map's form and what it found. `POST /v1/map` answers at once and the server keeps no URLs (jobs spec "Map, scope
 * and sitemaps"), so the run is kept in its browser history entry (HTML §7.4 session history, `history.state`): back,
 * forward and reload show it again, and nothing leaves the browser (D-1215). */
export interface MapRun {
  form: MapFormState;
  result: MapResult;
}

/** The history state member that holds the run. */
const MAP_RUN = "mapRun";

function isStrings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

/** History state is any structured-cloneable value another page may have written, so it is checked before use. */
function isMapResult(value: unknown): value is MapResult {
  if (!isJsonObject(value) || !isJsonObject(value.sources)) return false;
  return isStrings(value.urls) && typeof value.truncated === "boolean";
}

function isMapForm(value: unknown): value is MapFormState {
  return isJsonObject(value) && typeof value.url === "string" && isJsonObject(value.options);
}

/** The map run a history entry's `state` holds, or null for none. */
export function mapRunOf(state: unknown): MapRun | null {
  if (!isJsonObject(state)) return null;
  const run = state[MAP_RUN];
  if (!isJsonObject(run) || !isMapResult(run.result) || !isMapForm(run.form)) return null;
  return { form: run.form, result: run.result };
}

/** The map run of the current history entry, and that entry's `key`, which keys the run's output so each entry's
 * selection and page are its own. Each time an entry with a run is shown, its form fills the bar (`setForm`). `keep`
 * adds an entry at `/map`, out of any shown job, holding a new run. */
export function useMapRun(setForm: (form: MapFormState) => void) {
  const location = useLocation();
  const navigate = useNavigate();
  const run = mapRunOf(location.state);
  // The entry whose run is in the form; null once an entry without one is shown, so coming back restores it again.
  const [shown, setShown] = useState<string | null>(null);
  if (run === null && shown !== null) setShown(null);
  if (run !== null && location.key !== shown) {
    // React's "adjusting state when a prop changes": the form follows the entry in the same render.
    setShown(location.key);
    setForm(run.form);
  }
  return {
    run,
    key: location.key,
    keep: (form: MapFormState, result: MapResult) => {
      // Committed at once, so no frame shows the page between the answer and its entry.
      void navigate(
        { pathname: location.pathname, search: "" },
        { state: { [MAP_RUN]: { form, result } satisfies MapRun }, flushSync: true },
      );
    },
  };
}
