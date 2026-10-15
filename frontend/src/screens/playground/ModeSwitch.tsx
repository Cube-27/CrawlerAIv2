import { Tabs, Typography } from "@heroui/react";
import { MODE_GROUPS, type ModeId } from "./modes";

/** The mode switch: a tab per mode, each a link to its route, under its group's caption, so back and forward move
 * between modes. */
export function ModeSwitch({ current }: Readonly<{ current: ModeId }>) {
  return (
    <nav aria-label="Mode" className="flex flex-wrap items-end gap-6">
      {MODE_GROUPS.map((group) => (
        <div key={group.caption} className="flex flex-col gap-1">
          <Typography.Paragraph size="sm" color="muted">
            {group.caption}
          </Typography.Paragraph>
          <Tabs variant="secondary" selectedKey={current}>
            <Tabs.ListContainer>
              <Tabs.List aria-label={group.caption}>
                {group.modes.map((mode) => (
                  <Tabs.Tab key={mode.id} id={mode.id} href={mode.href}>
                    {mode.label}
                    <Tabs.Indicator />
                  </Tabs.Tab>
                ))}
              </Tabs.List>
            </Tabs.ListContainer>
          </Tabs>
        </div>
      ))}
    </nav>
  );
}
