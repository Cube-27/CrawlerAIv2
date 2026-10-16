import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApiClient } from "../../app/auth";
import { getProjectSettings, saveProjectSettings, type ProjectSettings } from "../project";
import { unwrap } from "./query";

const PROJECT_SETTINGS = ["project", "settings"] as const;

export function useProjectSettings() {
  const client = useApiClient();
  return useQuery({
    queryKey: PROJECT_SETTINGS,
    queryFn: () => unwrap(getProjectSettings(client)),
  });
}

/** The answer is the saved settings: they replace the cached ones, with no read. */
export function useSaveProjectSettings() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectSettings) => unwrap(saveProjectSettings(client, body)),
    onSuccess: (saved) => {
      queryClient.setQueryData(PROJECT_SETTINGS, saved);
    },
  });
}
