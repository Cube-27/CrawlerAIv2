import { FieldError, InputGroup, TextField } from "@heroui/react";

/** RFC 3986 §3: a URL with an authority starts with its scheme and `://`. The bar shows `https://`, so text typed
 * without one gets it; `host:port` (RFC 3986 §3.2) has no `//`, so it is a host, not a scheme. */
const HAS_SCHEME = /^[a-z][a-z\d+.-]*:\/\//i;

/** The URL the bar's text stands for: trimmed, with the `https://` the bar shows when it has no scheme. */
export function requestUrl(text: string): string {
  const url = text.trim();
  return url === "" || HAS_SCHEME.test(url) ? url : `https://${url}`;
}

/** The command bar's URL (frontend spec), with an `https://` prefix. Its name is the request member a server error
 * names. */
export function UrlInput({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (url: string) => void }>) {
  return (
    <TextField aria-label="URL" isRequired name="url" value={value} onChange={onChange}>
      <InputGroup fullWidth>
        <InputGroup.Prefix>https://</InputGroup.Prefix>
        <InputGroup.Input autoComplete="off" inputMode="url" placeholder="example.com" />
      </InputGroup>
      <FieldError />
    </TextField>
  );
}
