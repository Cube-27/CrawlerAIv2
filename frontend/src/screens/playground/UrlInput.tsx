import { FieldError, Input, TextField } from "@heroui/react";

/** RFC 3986 §3: a URL with an authority starts with its scheme and `://`. Text typed without a scheme gets
 * `https://`; `host:port` (RFC 3986 §3.2) has no `//`, so it is a host, not a scheme. */
const HAS_SCHEME = /^[a-z][a-z\d+.-]*:\/\//i;

/** The URL the bar's text stands for: trimmed, with `https://` added when it has no scheme. */
export function requestUrl(text: string): string {
  const url = text.trim();
  return url === "" || HAS_SCHEME.test(url) ? url : `https://${url}`;
}

/** The command bar's URL (frontend spec), as a plain input. Its name is the request member a server error
 * names. */
export function UrlInput({
  value,
  onChange,
}: Readonly<{ value: string; onChange: (url: string) => void }>) {
  return (
    <TextField aria-label="URL" isRequired name="url" value={value} onChange={onChange}>
      <Input fullWidth autoComplete="off" inputMode="url" placeholder="example.com" />
      <FieldError />
    </TextField>
  );
}
