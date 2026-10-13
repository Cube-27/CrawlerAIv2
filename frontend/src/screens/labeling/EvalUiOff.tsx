import { Typography } from "@heroui/react";
import { EmptyView } from "../../components/EmptyView";

export function EvalUiOff() {
  return (
    <EmptyView title="The labeling API is off.">
      Start the backend with <Typography.Code>CRAWLERAI_EVAL_UI=true</Typography.Code> to label
      pages.
    </EmptyView>
  );
}
