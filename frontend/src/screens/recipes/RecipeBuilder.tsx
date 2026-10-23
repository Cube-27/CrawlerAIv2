import { Link, Typography } from "@heroui/react";
import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { parseFieldTypes } from "../../api/field";
import { useCallList } from "../../api/hooks/recipes";
import { problemOf } from "../../api/hooks/query";
import { MAX_SAMPLES } from "../../api/recipes";
import type { SchemaDef } from "../../api/schemas";
import { EmptyView } from "../../components/EmptyView";
import { keyedTexts } from "../../components/keys";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { ProblemAlert } from "../../components/ProblemAlert";
import { SchemaSelect } from "../../components/SchemaSelect";
import { Section } from "../../components/Section";
import { CallList, type SampleNumber } from "./CallList";
import { endpointKey, endpointText, matchLines, ownSiteFirst } from "./endpoints";
import { recipesPath } from "./paths";
import { SampleForm, SampleList, type Sample } from "./Samples";

/** The fewest samples a recipe is built from: one page cannot tell a call's fixed parts from those the URL varies. */
const MIN_SAMPLES = 2;

function samplesHelp(count: number): string {
  if (count < MIN_SAMPLES)
    return `Capture at least ${String(MIN_SAMPLES)} pages, at most ${String(MAX_SAMPLES)}.`;
  if (count >= MAX_SAMPLES) return `${String(MAX_SAMPLES)} samples: remove one to capture another.`;
  return `${String(count)} samples; up to ${String(MAX_SAMPLES)}.`;
}

/** Step 3 and 4: the samples' calls by endpoint, and the main call chosen from them. */
function CallSteps({
  samples,
  main,
  onPick,
}: Readonly<{ samples: readonly Sample[]; main: string | null; onPick: (key: string) => void }>) {
  const ids = useMemo(() => samples.map(({ captureId }) => captureId), [samples]);
  const calls = useCallList(ids);
  const problem = problemOf(calls.error);
  const sampleOf: SampleNumber = (captureId) => ids.indexOf(captureId) + 1;
  const endpoints = calls.data === undefined ? [] : ownSiteFirst(calls.data.endpoints);
  const chosen = endpoints.find((endpoint) => endpointKey(endpoint) === main);
  return (
    <>
      <Section title="3. Calls">
        <Typography.Paragraph size="sm" color="muted">
          Every call the sample pages made, grouped by endpoint, the page&apos;s own site first,
          with the paths that read each field of the schema.
        </Typography.Paragraph>
        {calls.isPending ? <LoadingView label="Loading the calls" /> : null}
        {problem === null ? null : <ProblemAlert problem={problem} />}
        {calls.isSuccess && endpoints.length === 0 ? (
          <EmptyView title="No calls">
            The pages made no call the capture keeps (JSON, Flight or HTML fragments).
          </EmptyView>
        ) : null}
        <CallList
          endpoints={endpoints}
          samples={ids.length}
          sampleOf={sampleOf}
          main={main}
          onPick={onPick}
        />
      </Section>
      <Section title="4. Main call">
        {chosen === undefined ? (
          <Typography.Paragraph size="sm" color="muted">
            Choose the call that answers with the page&apos;s record: &quot;Use as main call&quot;
            on its group.
          </Typography.Paragraph>
        ) : (
          <div className="flex flex-col gap-2">
            <Typography.Paragraph className="font-mono text-sm break-all">
              {endpointText(chosen)}
            </Typography.Paragraph>
            <ul aria-label="Main call fields" className="flex flex-col gap-1 font-mono text-sm">
              {keyedTexts(chosen.fields.flatMap((match) => matchLines(match, ids.length))).map(
                ({ key, text }) => (
                  <li key={key}>{text}</li>
                ),
              )}
            </ul>
          </div>
        )}
      </Section>
    </>
  );
}

/** Building a custom recipe for the site, step by step: 1. the schema, 2. two to five sample pages captured in the
 * browser with their page steps and request context, each with its records, 3. their calls by endpoint, with where
 * each carries the schema's fields, a call opening in a drawer with its headers, body, answer and the HAR, and 4. the
 * main call. Calls, paths and headers are shown here only (a stated exception to hiding internals). Changing the
 * schema starts over: the samples were read for the one chosen. */
export function RecipeBuilder() {
  const { host = "" } = useParams();
  const [schema, setSchema] = useState<SchemaDef | null>(null);
  const [samples, setSamples] = useState<readonly Sample[]>([]);
  const [main, setMain] = useState<string | null>(null);
  const fieldTypes = useMemo(
    () => (schema === null ? {} : parseFieldTypes(schema.fields, schema.field_order)),
    [schema],
  );
  return (
    <section className="flex flex-col gap-stack">
      <PageHeader
        title={`New recipe for ${host}`}
        actions={<Link href={recipesPath(host)}>All recipes</Link>}
      />
      <Section title="1. Schema">
        <SchemaSelect
          value={schema?.id ?? ""}
          onChange={(_id, chosen) => {
            setSchema(chosen);
            setSamples([]);
            setMain(null);
          }}
        />
      </Section>
      {schema === null ? null : (
        <Section title="2. Sample pages">
          <Typography.Paragraph size="sm" color="muted">
            {samplesHelp(samples.length)}
          </Typography.Paragraph>
          <SampleList
            samples={samples}
            fieldTypes={fieldTypes}
            onRemove={(captureId) => {
              setSamples((kept) => kept.filter((sample) => sample.captureId !== captureId));
            }}
          />
          <SampleForm
            schema={schema}
            isFull={samples.length >= MAX_SAMPLES}
            onCaptured={(sample) => {
              setSamples((kept) => [...kept, sample]);
            }}
          />
        </Section>
      )}
      {samples.length === 0 ? null : <CallSteps samples={samples} main={main} onPick={setMain} />}
    </section>
  );
}
