import { Button, toast } from "@heroui/react";
import type { ConfigDetail } from "../../api/configs";
import { useLearnSite } from "../../api/hooks/configs";

/** "Learn now" for the config's site and schema version (`POST /v1/sites/{host}/learn`, D-0592). The server refuses
 * while a config is active or a run is in flight (409); after a refusal, "Learn anyway" asks again with `force`. The
 * screen shows `learn.error` under its header. */
export function useLearn(config: ConfigDetail) {
  const learn = useLearnSite(config.site);
  const start = (force: boolean) => {
    learn.mutate(
      { schema_id: config.schema_id, force },
      {
        onSuccess: (jobId) => {
          toast.success(`Learning started as job ${jobId}.`);
        },
      },
    );
  };
  return { learn, start };
}

export function LearnButtons({ learn, start }: Readonly<ReturnType<typeof useLearn>>) {
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
        onPress={() => {
          start(false);
        }}
      >
        Learn now
      </Button>
    </>
  );
}
