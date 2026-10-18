import { Button, Description, FieldError, TextArea, TextField, Tooltip } from "@heroui/react";
import { FileArrowUp } from "@gravity-ui/icons";
import { useRef } from "react";
import { lines } from "../pageRequest";
import { appendUrls, csvUrls } from "./urls";

/** RFC 4180 §3 registers `text/csv`; files saved without that type still end in `.csv`. */
const CSV_FILES = ".csv,text/csv";

/** The Batch command bar's URL list (frontend spec): one URL per line, with a live count, and an icon in the box that
 * appends the URLs of a CSV file. Its name is the request member a server error names. */
export function UrlList({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (urls: string) => void }>) {
  const fileInput = useRef<HTMLInputElement>(null);
  const count = lines(value).length;
  return (
    <div className="relative">
      <TextField aria-label="URLs" isRequired name="urls" value={value} onChange={onChange}>
        {/* Ten lines show at once; a longer list scrolls inside the box, which keeps its height. */}
        <TextArea
          rows={10}
          className="resize-none overflow-y-auto"
          spellCheck={false}
          placeholder="One URL per line"
        />
        <Description>
          {count} {count === 1 ? "URL" : "URLs"}
        </Description>
        <FieldError />
      </TextField>
      <div className="absolute top-2 right-2">
        <Tooltip delay={0}>
          <Button
            isIconOnly
            size="sm"
            variant="ghost"
            aria-label="Upload a CSV of URLs"
            onPress={() => fileInput.current?.click()}
          >
            <FileArrowUp aria-hidden="true" />
          </Button>
          <Tooltip.Content>Upload a CSV of URLs</Tooltip.Content>
        </Tooltip>
      </div>
      {/* The file picker the icon opens; hidden, so the icon is the one control. */}
      <input
        ref={fileInput}
        type="file"
        accept={CSV_FILES}
        hidden
        aria-label="CSV file"
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (file !== undefined)
            void file.text().then((text) => {
              onChange(appendUrls(value, csvUrls(text)));
            });
        }}
      />
    </div>
  );
}
