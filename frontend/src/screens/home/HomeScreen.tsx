import { Card, Link, Skeleton, Typography } from "@heroui/react";
import { Layers, Magnifier, Thunderbolt } from "@gravity-ui/icons";
import type { ComponentType, ReactNode, SVGProps } from "react";
import { useJobs } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { useSchemas } from "../../api/hooks/schemas";
import { useLlmCostReport } from "../../api/hooks/usage";
import { EmptyView } from "../../components/EmptyView";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { PAGE_SIZE } from "../../components/PagedTable";
import { ProblemAlert } from "../../components/ProblemAlert";
import { formatUsd } from "../../components/usd";
import { JobRows } from "../jobs/JobTable";
import { rangeStart } from "../settings/costs";

/** The recent jobs the overview lists; `h-table-recent` in theme.css holds this many rows. */
const RECENT_JOBS = 8;

const NO_FILTERS = { kind: null, status: null } as const;

interface Action {
  href: string;
  title: string;
  description: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
}

const ACTIONS: readonly Action[] = [
  {
    href: "/scrape",
    title: "Scrape a page",
    description: "Fetch one URL as Markdown, HTML, links or structured fields.",
    icon: Magnifier,
  },
  {
    href: "/jobs",
    title: "Run a job",
    description: "Batch scrape, crawl, map or extract many pages at once.",
    icon: Thunderbolt,
  },
  {
    href: "/schemas/new",
    title: "Define a schema",
    description: "Describe the fields to extract; learning turns them into a site config.",
    icon: Layers,
  },
];

function ActionTile({ action }: Readonly<{ action: Action }>) {
  const Icon = action.icon;
  return (
    <Link href={action.href} className="action-tile">
      <span className="action-tile-icon" aria-hidden="true">
        <Icon />
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <Typography.Paragraph weight="medium">{action.title}</Typography.Paragraph>
        <Typography.Paragraph size="sm" color="muted">
          {action.description}
        </Typography.Paragraph>
      </span>
    </Link>
  );
}

/** One headline number. `value` is null while it loads; the tile keeps its size in every state. */
function StatTile({
  label,
  value,
  caption,
}: Readonly<{ label: string; value: string | null; caption: string }>) {
  return (
    <Card>
      <Card.Header>
        <Card.Description>{label}</Card.Description>
      </Card.Header>
      <Card.Content>
        {value === null ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <span className="stat-value">{value}</span>
        )}
        <Typography.Paragraph size="sm" color="muted">
          {caption}
        </Typography.Paragraph>
      </Card.Content>
    </Card>
  );
}

function RunningJobs() {
  const jobs = useJobs({
    filters: { kind: null, status: "running" },
    cursor: null,
    limit: PAGE_SIZE,
  });
  if (jobs.isError) return <StatTile label="Jobs running" value="—" caption="Could not load" />;
  if (!jobs.isSuccess) return <StatTile label="Jobs running" value={null} caption="Loading" />;
  const more = jobs.data.next_cursor === null ? "" : "+";
  return (
    <StatTile
      label="Jobs running"
      value={`${String(jobs.data.items.length)}${more}`}
      caption="Batch scrapes, crawls, maps, extracts and learning runs"
    />
  );
}

function SchemaCount() {
  const schemas = useSchemas();
  if (schemas.isError) return <StatTile label="Schemas" value="—" caption="Could not load" />;
  if (!schemas.isSuccess) return <StatTile label="Schemas" value={null} caption="Loading" />;
  const names = new Set(schemas.data.map((schema) => schema.name));
  return (
    <StatTile
      label="Schemas"
      value={String(names.size)}
      caption={`${String(schemas.data.length)} versions in all`}
    />
  );
}

function LlmCost() {
  const report = useLlmCostReport(rangeStart("30"));
  const label = "LLM cost, last 30 days";
  if (report.isError) return <StatTile label={label} value="—" caption="Could not load" />;
  if (!report.isSuccess) return <StatTile label={label} value={null} caption="Loading" />;
  const { estimated_usd: usd, calls } = report.data.total;
  return (
    <StatTile
      label={label}
      value={usd === null ? "—" : formatUsd(usd)}
      caption={usd === null ? `${String(calls)} calls, cost unknown` : `${String(calls)} calls`}
    />
  );
}

function RecentJobsContent() {
  const jobs = useJobs({ filters: NO_FILTERS, cursor: null, limit: RECENT_JOBS });
  const problem = problemOf(jobs.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!jobs.isSuccess) return <LoadingView label="Loading recent jobs" />;
  if (jobs.data.items.length === 0) {
    return (
      <EmptyView title="No jobs yet">Scrape a page or run a job, and it shows up here.</EmptyView>
    );
  }
  return <JobRows jobs={jobs.data.items} />;
}

function Section({
  title,
  action,
  children,
}: Readonly<{ title: string; action?: ReactNode; children: ReactNode }>) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <Typography.Heading level={2}>{title}</Typography.Heading>
        {action}
      </div>
      {children}
    </section>
  );
}

/** The start screen: what to do first, the headline numbers, and the latest jobs. */
export function HomeScreen() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Overview"
        description="Turn pages into Markdown and structured records, then let learning take over."
      />
      <Section title="Get started">
        <div className="grid gap-3 sm:grid-cols-3">
          {ACTIONS.map((action) => (
            <ActionTile key={action.href} action={action} />
          ))}
        </div>
      </Section>
      <Section title="At a glance">
        <div className="grid gap-3 sm:grid-cols-3">
          <RunningJobs />
          <SchemaCount />
          <LlmCost />
        </div>
      </Section>
      <Section title="Recent jobs" action={<Link href="/jobs">View all</Link>}>
        {/* Every state fills the same box: nothing below moves while it loads (no layout shift). */}
        <div className="h-table-recent overflow-auto">
          <RecentJobsContent />
        </div>
      </Section>
    </div>
  );
}
