import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import { getLlmCostReport } from "../usage";
import { unwrap } from "./query";

/** The LLM cost report from `start` through today. */
export function useLlmCostReport(start: string) {
  const client = useApiClient();
  return useQuery({
    queryKey: ["usage", "llm", start],
    queryFn: () => unwrap(getLlmCostReport(client, start)),
  });
}
