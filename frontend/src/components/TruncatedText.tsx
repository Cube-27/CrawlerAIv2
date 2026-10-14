import { Tooltip } from "@heroui/react";

/** Text cut to its cell's fixed width (DESIGN.md: data tables), shown in full on hover or focus in a tooltip, which
 * overlays the table and so moves nothing. */
export function TruncatedText({ text }: Readonly<{ text: string }>) {
  return (
    <Tooltip delay={0}>
      <Tooltip.Trigger aria-label={text} className="block truncate">
        {text}
      </Tooltip.Trigger>
      <Tooltip.Content>{text}</Tooltip.Content>
    </Tooltip>
  );
}
