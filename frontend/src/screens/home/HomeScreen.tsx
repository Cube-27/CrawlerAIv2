import { PageHeader } from "../../components/PageHeader";

export function HomeScreen() {
  return (
    <section className="flex flex-col gap-2">
      <PageHeader title="Overview" />
      <p className="text-muted">Screens arrive with the API they use (SPEC-12).</p>
    </section>
  );
}
