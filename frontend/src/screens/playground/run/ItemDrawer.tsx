import { Drawer, Typography } from "@heroui/react";
import { JsonView } from "../../../components/JsonView";

/** One page's JSON in a drawer from the right, over the results table: its `json_values` item (SPEC-14 §4.3), or its
 * page output for a job without a schema (SPEC-10 §4.2). `position` is the page's place in the job (from 1), which
 * names its file; `onClose` closes the drawer. */
export function ItemDrawer({
  url,
  value,
  position,
  onClose,
}: Readonly<{ url: string; value: unknown; position: number; onClose: () => void }>) {
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
                {url}
              </Typography.Paragraph>
            </Drawer.Header>
            <Drawer.Body>
              <JsonView
                label="Page JSON"
                value={value}
                filename={`page-${String(position)}.json`}
              />
            </Drawer.Body>
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  );
}
