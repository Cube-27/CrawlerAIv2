# Frontend design conventions

How the frontend (`frontend/`) is built on HeroUI v3. Product screens are specified in SPEC-12; this file holds
the conventions every screen follows. Toolchain: SPEC-00 §4.3.

## Stack

- HeroUI v3 is React Aria Components styled by HeroUI's own CSS: `@heroui/react` has `react-aria-components` as a
  peer, and `@heroui/styles` holds the CSS. Both are MIT and pinned in `frontend/package.json`. Its API differs
  from HeroUI v2 (the NextUI lineage): don't use v2 docs or v2 packages.
- Import UI only from `@heroui/react`. It covers forms, tables, pagination, toasts, modals, empty states, skeletons
  and toolbars. Don't import `react-aria-components` (or `react-aria`, `@react-aria/*`, `@react-stately/*`)
  directly in app code: HeroUI already wraps it with its styles.
- Never add another UI or component library, and never hand-write component CSS. Icons come from one set,
  `@gravity-ui/icons` (MIT, the set HeroUI's documentation uses).
- Typefaces are bundled with the app from Fontsource packages (SIL OFL 1.1), imported by `src/app/theme.css`. No page
  loads a font, script or style from a third-party service.
- `tools/theme_only_check.py` enforces this and the theming rule below, in CI (the frontend job), `make check` and
  pre-commit. App code may import only `@heroui/react`, the icon set and the non-UI runtime packages it lists; a
  new runtime dependency is added to that list in the PR that adds it.

## Reference

Linear, for layout and patterns: a quiet, dense application UI. That means left sidebar navigation, list- and
table-first screens, a compact page header (title left, primary action right), subtle borders over shadows, a
neutral palette with one accent, keyboard-first use, and few modals. The reference guides layout, density and
pattern choices only. Don't copy its styles or any brand asset: visual values start from HeroUI's defaults, and every
tweak goes in `src/app/theme.css` (today: the Inter and JetBrains Mono typefaces, a neutral palette with one indigo
accent, a compact type scale and outlined cards).

## Theming

The rule: there is no in-house design system. A visual change is an edit to `src/app/theme.css` only, never to a
screen or component.
- HeroUI v3 components are used as they are, with their own variants and props (`variant`, `color`, `size`,
  `status`). There are no wrapper components that restyle HeroUI.
- Every visual value is a variable in `src/app/theme.css`: color, radius, spacing beyond Tailwind's default layout
  scale, and widths such as the content maximum. HeroUI's variables are overridden under `:root` and
  `[data-theme="dark"]`; layout sizes are Tailwind theme variables under `@theme`, used through the utility they
  generate (`--container-content` gives `max-w-content`).
- Tailwind is only for layout utilities on the default scale (flex, grid, gap, padding, width, breakpoints) and
  HeroUI's semantic tokens (`bg-background`, `text-foreground`, `border-border`, `text-danger`). Text styles come
  from HeroUI's `Typography`, not from `text-*` size or `font-*` utilities.
- The check fails on color literals (hex, `rgb()`, `rgba()`, `hsl()`, `oklch()`), Tailwind arbitrary values
  (`max-w-[1280px]`), Tailwind palette colors (`bg-blue-500`), `style=` props, and any CSS file other than
  theme.css, across `frontend/src` except tests and generated files.

## Light and dark

- The theme is the `data-theme` attribute (`light` or `dark`) on `<html>`; HeroUI v3 keys dark mode on it.
- A viewer who never chose follows `prefers-color-scheme`. An explicit choice is persisted per viewer in
  `localStorage` (`crawlerai.theme`), and only an explicit choice is written (DECISIONS D-0054).
- Every `localStorage` access is wrapped in try/catch: storage can be missing or throw, and the page must render
  correctly without it.
- The theme is applied before paint, so no frame shows in the old theme. All of this lives in `src/app/theme.ts`.

## Layout

- One app shell (`src/app/shell.tsx`): a left sidebar and the content area. The sidebar holds the product mark, the
  navigation in labelled groups with one icon per item (the current screen is marked by `aria-current`, shown with a
  filled background), and at its foot Settings and the dark-theme toggle. The content sits on an inset
  panel beside it.
- Content is at most 1280px wide (`--container-content` in theme.css).
- At phone width the sidebar moves above the content, gutters are 16px, and nothing scrolls horizontally.

## Components

- Every interactive element is a HeroUI component: Button, TextField, Select, Table, Modal, Tabs, Toast, Switch,
  Link. Never hand-roll a focusable control.
- Forms use React Aria's form validation.
- Tables use the HeroUI Table with keyboard navigation.
- Status is shown with text and an icon, never with color alone.
- Links navigate through react-router: the shell passes `navigate` and `useHref` to HeroUI's `RouterProvider`.

## Patterns

One way to do each recurring job. Each is composed from HeroUI components used as they are, and lives once: as a
small composition in `src/components/`, or, where HeroUI's own API is the whole pattern, as the rule below. Screens
use it instead of composing their own. Each line ends with how it follows the reference (Linear).

| Job | The one way | Reference |
|---|---|---|
| Page title and actions | `PageHeader`: the page's one h1, badges beside it, an optional one-line description under it, primary actions on the right. | Compact header, title left, primary action right. |
| Open by key | `LookupForm`: one field with a search icon and its button on one row, to open an item by its id or host. | Quick open, no form page. |
| Dates and times | `Timestamp`: an API timestamp as a short local date and 24-hour time in a `<time>` element, the exact instant in its tooltip; a missing one is a dash. Never show raw RFC 3339 text. | Quiet, readable metadata. |
| Headline numbers | A HeroUI `Card` per number: label, value (`stat-value`), one muted line of context; a `Skeleton` while it loads and a dash when it can't load, in the same footprint. | Dense overview, no charts for a single number. |
| Forms | HeroUI `Form`; one field per row, label above (two closely related fields, such as a pair of globs or of limits, may share a row in a two-column grid from `sm`) (`Label`), message below (`FieldError`, React Aria validation). A problem from the API shows above the fields as a `ProblemAlert`. Buttons go in `FormActions` after the fields: right-aligned, secondary (Cancel) first, primary last. | Dense single-column forms, one primary action. |
| Field groups | HeroUI `Fieldset` with `Fieldset.Legend`. | Grouping by spacing and labels, not boxes. |
| Data tables | HeroUI `Table`. Sorting: `allowsSorting` on `Table.Column` with `sortDescriptor`/`onSortChange` on the table. Pagination: `PagedTable`, a fixed-height box of `PAGE_SIZE` rows with `TablePagination` under it (previous/next by cursor, SPEC-07 §4.6); loading and problem states fill the same box, so paging moves nothing. Fixed column widths (`table-fixed`, a width per column, `truncate` in cells). Row actions: a row `href` to open the item; other actions on the item's page, or in a HeroUI `Dropdown` in the row's last column. | Table-first screens; open an item by its row. |
| Empty state | `EmptyView`: what is missing and how to get it, with an optional action. | Quiet empty states with one next step. |
| Loading state | `LoadingView` (a named HeroUI `Spinner`) in place of the content; a HeroUI `Skeleton` where the layout is known. | No layout jump. |
| Error state | `ProblemAlert` for every RFC 9457 problem: its title, its detail, then any per-field lines. Other alerts use HeroUI `Alert` with a `status`. | Errors inline, where they happened. |
| Status display | `StatusLabel`: a HeroUI `Chip` with one icon and one color per tone. Each domain maps each of its status values to one tone, once, next to its type (for example `LabelStatusChip` for label statuses). | Neutral palette; status by icon and text. |
| Confirmations | `ConfirmDialog` (HeroUI `AlertDialog`), only before an action that can't be undone. Cancel first, the action last. | Few modals. |
| Notifications | `toast` from `@heroui/react` (for example `toast.success`); the one `Toast.Provider` is in the shell. Use it for the outcome of an action, never for an error the user must act on. | Brief, out-of-the-way confirmations. |

## Accessibility

React Aria supplies the behaviour; these rules keep it intact.
- Every control has an accessible name.
- Everything is reachable by keyboard.
- Oxlint's `jsx-a11y` plugin runs the strict rule set (`frontend/vite.config.ts`), and lint runs in CI.
- Focus-visible styles are never removed.

## Showing extraction results

These follow from the product's precision rules (ARCHITECTURE §10, §13.1).
- An abstained field is rendered as "—" with its reason on hover, never as an empty string.
- `calibrated=false` is rendered as a visible badge.
- `confidence` is rendered as a number, not a bar: a bar implies a calibration the value may not have.
- Screens show a field only through the shared compositions in `src/components/`: `FieldValue` (value by type,
  or "—" with reason and status), `FieldStatusBadge`, `ConfidenceCell` and `LocatorText`.

## Charts

Core screens use none. If a later spec adds one, it follows the dataviz guidance and the theming rules above.
