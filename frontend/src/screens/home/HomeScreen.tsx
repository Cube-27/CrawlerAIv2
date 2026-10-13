import { Typography } from "@heroui/react";
import { PageHeader } from "../../components/PageHeader";

export function HomeScreen() {
  return (
    <section className="flex flex-col gap-2">
      <PageHeader title="Overview" />
      <Typography.Paragraph color="muted">
        Screens arrive with the API they use (SPEC-12).
      </Typography.Paragraph>
    </section>
  );
}
