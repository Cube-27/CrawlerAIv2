# Frontend design conventions

How the frontend (`frontend/`) is built on HeroUI v3. Product screens are specified in SPEC-12; this file holds
the conventions every screen follows. Toolchain: SPEC-00 §4.3.

HeroUI v3 (`@heroui/react` and `@heroui/styles`, MIT, pinned in `frontend/package.json`) is built on React Aria
Components and Tailwind CSS v4. Its API differs from HeroUI v2 (the NextUI lineage): don't use v2 docs or v2
packages.

## Theming

- Colors, radius and spacing come from HeroUI's CSS-variable theme layer. Tailwind utilities use HeroUI's semantic
  tokens (`bg-background`, `text-foreground`, `border-border`), never palette colors chosen per component.
- Project overrides live only in `src/app/theme.css`, as HeroUI variables under `:root` and `[data-theme="dark"]`.
- No hard-coded hex, rgb or hsl values in components.

## Light and dark

- The theme is the `data-theme` attribute (`light` or `dark`) on `<html>`; HeroUI v3 keys dark mode on it.
- A viewer who never chose follows `prefers-color-scheme`. An explicit choice is persisted per viewer in
  `localStorage` (`crawlerai.theme`), and only an explicit choice is written (DECISIONS D-0054).
- Every `localStorage` access is wrapped in try/catch: storage can be missing or throw, and the page must render
  correctly without it.
- The theme is applied before paint, so no frame shows in the old theme. All of this lives in `src/app/theme.ts`.

## Layout

- One app shell: a top bar, a left nav and the content area (`src/app/shell.tsx`).
- Content is at most 1280px wide.
- At phone width the nav moves above the content, gutters are 16px, and nothing scrolls horizontally.

## Components

- Every interactive element is a HeroUI component: Button, TextField, Select, Table, Modal, Tabs, Toast, Switch,
  Link. Never hand-roll a focusable control.
- Forms use React Aria's form validation.
- Tables use the HeroUI Table with keyboard navigation.
- Status is shown with text and an icon, never with color alone.
- Links navigate through react-router: the shell passes `navigate` and `useHref` to HeroUI's `RouterProvider`.

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
