import { PageHeader } from "../../components/PageHeader";
import { LlmCostSection } from "./LlmCostSection";

/** Settings and usage of this deployment (SPEC-12 §4.3): for now, the LLM cost history. */
export function SettingsScreen() {
  return (
    <section className="flex flex-col gap-6">
      <PageHeader title="Settings" />
      <LlmCostSection />
    </section>
  );
}
