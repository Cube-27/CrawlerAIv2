import { Card, Link, Skeleton, Typography } from "@heroui/react";
import { Layers, Magnifier, Thunderbolt } from "@gravity-ui/icons";
import type { UseQueryResult } from "@tanstack/react-query";
import type { ComponentType, SVGProps } from "react";
import { useJobs } from "../../api/hooks/jobs";
import { problemOf } from "../../api/hooks/query";
import { useSchemas } from "../../api/hooks/schemas";
import { useLlmCostReport } from "../../api/hooks/usage";
import { EmptyView } from "../../components/EmptyView";
import { LoadingView } from "../../components/LoadingView";
import { PageHeader } from "../../components/PageHeader";
import { PAGE_SIZE } from "../../components/PagedTable";
import { ProblemAlert } from "../../components/ProblemAlert";
import { Section } from "../../components/Section";
import { JobRows } from "../jobs/JobTable";
import { formatCost, formatCount, RANGES, rangeStart } from "../settings/costs";

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

interface Stat {
  value: string;
  caption: string;
}

/** One headline number from one query. Loading shows a skeleton and an error a dash; the caption is a single
 * truncated line (full text in its tooltip), so the tile keeps its size in every state (no layout shift). */
function StatTile<T>({
  label,
  query,
  stat,
}: Readonly<{ label: string; query: UseQueryResult<T>; stat: (data: T) => Stat }>) {
  let shown: Stat | null;
  if (query.isError) shown = { value: "—", caption: "Could not load" };
  else if (query.isSuccess) shown = stat(query.data);
  else shown = null;
  const caption = shown?.caption ?? "Loading";
  return (
    <Card>
      <Card.Header>
        <Card.Description>{label}</Card.Description>
      </Card.Header>
      <Card.Content>
        {shown === null ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <span className="stat-value">{shown.value}</span>
        )}
        <Typography.Paragraph size="sm" color="muted" className="truncate" title={caption}>
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
  return (
    <StatTile
      label="Jobs running"
      query={jobs}
      stat={({ items, next_cursor: more }) => ({
        value: `${String(items.length)}${more === null ? "" : "+"}`,
        caption: "Across every job kind",
      })}
    />
  );
}

function SchemaCount() {
  return (
    <StatTile
      label="Schemas"
      query={useSchemas()}
      stat={(schemas) => ({
        value: formatCount(new Set(schemas.map((schema) => schema.name)).size),
        caption: `${formatCount(schemas.length)} versions in all`,
      })}
    />
  );
}

function LlmCost() {
  return (
    <StatTile
      label={`LLM cost, ${RANGES["30"].toLowerCase()}`}
      query={useLlmCostReport(rangeStart("30"))}
      stat={({ total }) =>
        total.estimated_usd === null
          ? { value: "—", caption: formatCost(total) }
          : { value: formatCost(total), caption: `${formatCount(total.calls)} calls` }
      }
    />
  );
}

function RecentJobsContent() {
  // The Jobs screen's first page: one cached query for both screens, of which the overview shows the newest few.
  const jobs = useJobs({ filters: NO_FILTERS, cursor: null, limit: PAGE_SIZE });
  const problem = problemOf(jobs.error);
  if (problem !== null) return <ProblemAlert problem={problem} />;
  if (!jobs.isSuccess) return <LoadingView label="Loading recent jobs" />;
  if (jobs.data.items.length === 0) {
    return (
      <EmptyView title="No jobs yet">Scrape a page or run a job, and it shows up here.</EmptyView>
    );
  }
  return <JobRows jobs={jobs.data.items.slice(0, RECENT_JOBS)} />;
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
