import { Button, Modal } from "@heroui/react";
import type { ReactNode } from "react";

/** A create dialog opened by its button (`label`). `children` gets `close`, for the form's Cancel. */
export function JobDialog({
  label,
  title,
  children,
}: Readonly<{ label: string; title: string; children: (close: () => void) => ReactNode }>) {
  return (
    <Modal>
      <Button variant="secondary">{label}</Button>
      <Modal.Backdrop>
        <Modal.Container scroll="inside" size="lg">
          <Modal.Dialog>
            {({ close }) => (
              <>
                <Modal.CloseTrigger />
                <Modal.Header>
                  <Modal.Heading>{title}</Modal.Heading>
                </Modal.Header>
                <Modal.Body>{children(close)}</Modal.Body>
              </>
            )}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
