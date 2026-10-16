import { Button, Fieldset, Form, toast } from "@heroui/react";
import { useState } from "react";
import { useLearnSite } from "../../api/hooks/configs";
import { problemOf } from "../../api/hooks/query";
import { FormActions } from "../../components/FormActions";
import { ProblemAlert } from "../../components/ProblemAlert";
import { SchemaSelect } from "../../components/SchemaSelect";

/** "Learn now" for a site and schema (`POST /v1/sites/{host}/learn`, D-0592). The server refuses while a
 * config is active or a run is in flight (409); after a refusal, "Learn anyway" asks again with `force`. The screen
 * shows `learn.error`. */
export function useLearn({ site, schemaId }: Readonly<{ site: string; schemaId: string }>) {
  const learn = useLearnSite(site);
  const start = (force: boolean) => {
    learn.mutate(
      { schema_id: schemaId, force },
      {
        onSuccess: (jobId) => {
          toast.success(`Learning started as job ${jobId}.`);
        },
      },
    );
  };
  return { learn, start };
}

/** "Learn anyway" after a refusal, then "Learn now"; `submits` makes "Learn now" its form's submit button. */
export function LearnButtons({
  learn,
  start,
  submits = false,
}: Readonly<ReturnType<typeof useLearn> & { submits?: boolean }>) {
  return (
    <>
      {learn.isError ? (
        <Button
          variant="secondary"
          isPending={learn.isPending}
          onPress={() => {
            start(true);
          }}
        >
          Learn anyway
        </Button>
      ) : null}
      <Button
        isPending={learn.isPending}
        {...(submits
          ? { type: "submit" as const }
          : {
              onPress: () => {
                start(false);
              },
            })}
      >
        Learn now
      </Button>
    </>
  );
}

/** Learning a config for the site from a schema chosen here: the way to a site's first config. */
export function SiteLearnForm({ site }: Readonly<{ site: string }>) {
  const [schemaId, setSchemaId] = useState("");
  const learning = useLearn({ site, schemaId });
  const problem = problemOf(learning.learn.error);
  return (
    <Form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        learning.start(false);
      }}
    >
      <Fieldset>
        <Fieldset.Legend>Learn a config</Fieldset.Legend>
        <SchemaSelect value={schemaId} onChange={setSchemaId} />
      </Fieldset>
      <FormActions>
        <LearnButtons {...learning} submits />
      </FormActions>
      {/* Under the buttons: a refusal moves nothing above them. */}
      {problem === null ? null : <ProblemAlert problem={problem} />}
    </Form>
  );
}
