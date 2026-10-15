import { Drawer, Typography } from "@heroui/react";
import type { JsonValuesItem } from "../../../api/jobs";
import { JsonView } from "../../../components/JsonView";

/** One page's `json_values` item (SPEC-14 §4.3) in a drawer from the right, over the results table. `position` is the
 * page's place in the job (from 1), which names its file; `onClose` closes the drawer. */
export function ItemDrawer({
  item,
  position,
  onClose,
}: Readonly<{ item: JsonValuesItem; position: number; onClose: () => void }>) {
  return (
    <Drawer
      isOpen
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose();
      }}
    >
      <Drawer.Backdrop>
        <Drawer.Content placement="right">
          <Drawer.Dialog>
            <Drawer.CloseTrigger />
            <Drawer.Header>
              <Drawer.Heading>Page {position}</Drawer.Heading>
              <Typography.Paragraph size="sm" color="muted" className="truncate">
                {item.url}
              </Typography.Paragraph>
            </Drawer.Header>
            <Drawer.Body>
              <JsonView label="Page JSON" value={item} filename={`page-${String(position)}.json`} />
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
