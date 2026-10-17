import { Tabs } from "@heroui/react";
import { MODE_GROUPS, type ModeId } from "./modes";

/** The mode switch, centred over the command bar: a tab per mode, each a link to its route, so back and forward move
 * between modes. Each group is its own tab list, named by its caption for assistive technology but shown without it. */
export function ModeSwitch({ current }: Readonly<{ current: ModeId }>) {
  return (
    <nav aria-label="Mode" className="flex flex-wrap items-end justify-center gap-6">
      {MODE_GROUPS.map((group) => (
        <div key={group.caption}>
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
